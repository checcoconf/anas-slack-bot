"""Legge le fonti oltre ANAS (Bolzano, A22) una volta per giro: due richieste in tutto, nessuna verso ANAS.

- Primo giro di una fonte: tutto ciò che è già pubblicato viene salvato "in silenzio" (stato 3, come le
  ordinanze ANAS già in vigore all'installazione): niente valanga di messaggi, ma entra nel riepilogo di chi
  sceglie le zone.
- Poi: ogni avviso con un numero mai visto è una novità e segue il percorso normale (zone, messaggi).
- Una fonte che non risponde o cambia formato non ferma il giro: si salta e si riprova all'ora dopo;
  dopo FAIL_ALERT_RUNS giri falliti di fila l'admin viene avvisato (una volta).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable

import requests

from ..db import Database
from . import ID_OFFSET, SOURCE_LABELS, a22, bolzano

log = logging.getLogger(__name__)

FAIL_ALERT_RUNS = 6
TIMEOUT = 30


@dataclass
class FontiResult:
    new: dict[str, int] = field(default_factory=dict)       # fonte -> avvisi nuovi
    silent: dict[str, int] = field(default_factory=dict)    # fonte -> avvisi registrati al primo giro
    errors: dict[str, str] = field(default_factory=dict)    # fonte -> errore di questo giro
    alerts: list[str] = field(default_factory=list)         # messaggi per l'admin


def _http_get(url: str, user_agent: str) -> requests.Response:
    r = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": user_agent, "Connection": "close",
                                                    "Accept-Language": "it"})
    r.raise_for_status()
    return r


class FontiPoller:
    def __init__(self, db: Database, enabled: list[str], user_agent: str = "anas-bot",
                 get: Callable[[str], requests.Response] | None = None) -> None:
        self.db = db
        self.enabled = enabled
        self.get = get or (lambda url: _http_get(url, user_agent))

    def _read(self, source: str):
        if source == "bz":
            return bolzano.parse_feed(self.get(bolzano.FEED_URL).text)
        if source == "a22":
            return a22.parse_avvisi(json.loads(self.get(a22.API_URL).text))
        raise ValueError(f"fonte sconosciuta: {source}")

    def run(self, today: date, now=None) -> FontiResult:
        """now: data e ora locali del giro (per gli orari del bollettino di Bolzano); None = leggi sempre."""
        res = FontiResult()
        for source in self.enabled:
            if source == "bz" and now is not None and not bolzano.is_updated_now(now):
                log.info("Fonte %s: fuori dagli orari di aggiornamento del bollettino, non letta", SOURCE_LABELS[source])
                continue
            fail_key = f"fonte_{source}_failed"
            try:
                items = self._read(source)
            except Exception as exc:  # noqa: BLE001 - una fonte esterna non deve mai fermare il giro ANAS
                res.errors[source] = f"{type(exc).__name__}: {exc}"[:300]
                failed = int(self.db.get(fail_key, "0") or 0) + 1
                self.db.set(fail_key, str(failed))
                log.warning("Fonte %s non letta (%d giri di fila): %s", SOURCE_LABELS[source], failed, res.errors[source])
                if failed == FAIL_ALERT_RUNS:
                    res.alerts.append(f"⚠️ Fonte *{SOURCE_LABELS[source]}* non leggibile da {failed} giri: "
                                      f"{res.errors[source]}. Gli avvisi ANAS continuano normalmente.")
                continue
            if int(self.db.get(fail_key, "0") or 0) >= FAIL_ALERT_RUNS:
                res.alerts.append(f"✅ Fonte *{SOURCE_LABELS[source]}* di nuovo leggibile.")
            self.db.set(fail_key, "0")

            try:
                self._store(source, items, today, res)
            except Exception as exc:  # noqa: BLE001
                res.errors[source] = f"{type(exc).__name__}: {exc}"[:300]
                log.warning("Fonte %s letta ma non salvata: %s", SOURCE_LABELS[source], res.errors[source])
        return res

    def _store(self, source: str, items, today: date, res: FontiResult) -> None:
        seeded_key = f"fonte_{source}_seeded"
        first = self.db.get(seeded_key) != "1"
        known = self.db.known_among([o.ord_id for o in items])
        unseen = [o for o in items if o.ord_id not in known]
        new = [o for o in unseen if not o.is_expired(today)]
        for o in unseen:  # già scaduti: registrati in silenzio, così non si ripropongono a ogni giro
            self.db.save_ordinanza(o, o.excerpt, silent=first or o.is_expired(today))
        # avvisi spariti dalla fonte: sono finiti (la fonte li toglie a lavori conclusi). Senza questo
        # resterebbero "in vigore" per sempre e finirebbero nel riepilogo dei nuovi iscritti.
        lo = ID_OFFSET[source]
        gone = self.db.open_ids_in_range(lo, lo + 1_000_000_000, today) - {o.ord_id for o in items}
        if gone and items:  # una risposta vuota non chiude niente: potrebbe essere un guasto della fonte
            self.db.end_ordinanze(sorted(gone), today - timedelta(days=1))
            log.info("Fonte %s: %d avvisi conclusi (non più pubblicati)", SOURCE_LABELS[source], len(gone))
        if first:
            self.db.set(seeded_key, "1")
            res.silent[source] = len(unseen)
        else:
            res.new[source] = len(new)
        log.info("Fonte %s: %d avvisi utili, %d nuovi%s", SOURCE_LABELS[source], len(items),
                 len(unseen) if first else len(new),
                 " (primo giro: registrati senza avvisare)" if first else "")
