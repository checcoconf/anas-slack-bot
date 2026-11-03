"""Ciclo di raccolta delle ordinanze: avanza sugli ord_id a partire dal cursore.

Esempio con cursore = 1000 e MAX_GAP = 3:
    1001 trovato  -> salvato, cursore 1001
    1002 manca
    1003 trovato  -> salvato, cursore 1003, 1002 va tra i "mancanti"
    1004, 1005, 1006 mancano -> 3 buchi di fila: per ora non c'è altro, stop.
I "mancanti" (1002) vengono ricontrollati nei cicli successivi per 48 ore:
capita che un numero venga assegnato prima che il PDF sia pubblicato.

Dopo uno spegnimento il cursore è ancora nel database, quindi il primo ciclo
riprende esattamente da dove si era fermato.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable, Protocol

from .anas.client import TransientError
from .anas.parser import Ordinanza, parse_ordinanza
from .config import Config
from .db import Database

log = logging.getLogger(__name__)


class Source(Protocol):
    def url_for(self, ord_id: int) -> str: ...
    def fetch_text(self, ord_id: int) -> str | None: ...


class PdfSource:
    """Sorgente reale: scarica il PDF e ne estrae il testo."""

    def __init__(self, client, pdf_to_text: Callable[[bytes], str]) -> None:
        self.client = client
        self.pdf_to_text = pdf_to_text

    def url_for(self, ord_id: int) -> str:
        return self.client.url_for(ord_id)

    def fetch_text(self, ord_id: int) -> str | None:
        data = self.client.fetch_pdf(ord_id)
        if data is None:
            return None
        return self.pdf_to_text(data)


@dataclass
class PollResult:
    fetched: int = 0
    relevant: int = 0
    requests: int = 0
    more_pending: bool = False  # budget finito mentre trovavamo ancora ordinanze
    error: str = ""


RELEVANT = {"chiusura", "riapertura", "limite_velocita"}

# Salti esplorativi oltre un buco lungo: se la numerazione ANAS salta più di MAX_GAP
# numeri di fila, il passo-passo si fermerebbe sempre nello stesso punto. Questi
# assaggi più avanti se ne accorgono e fanno ripartire il bot dopo il buco.
LOOKAHEAD_OFFSETS = (50, 100, 200, 500)
MAX_BACKFILL = 500  # numeri del buco messi in ricontrollo, al massimo


class Poller:
    def __init__(self, db: Database, source: Source, cfg: Config) -> None:
        self.db = db
        self.source = source
        self.cfg = cfg

    def _store(self, ord_id: int, text: str, advance: bool) -> Ordinanza:
        o = parse_ordinanza(ord_id, text, self.source.url_for(ord_id))
        self.db.save_ordinanza(o, text, advance_cursor_to=ord_id if advance else None)
        log.info("ord_id=%s -> %s %s %s", ord_id, o.category, ",".join(o.roads), ",".join(o.provinces))
        return o

    def _lookahead_due(self) -> bool:
        last = float(self.db.get("anas_last_found_at", "0") or 0)
        return time.time() - last > self.cfg.lookahead_after_hours * 3600

    def _lookahead(self, res: PollResult) -> int:
        base = self.db.cursor() or 0
        requests = 0
        for off in LOOKAHEAD_OFFSETS:
            target = base + off
            requests += 1
            text = self.source.fetch_text(target)
            if text is None:
                continue
            log.warning("Buco lungo nella numerazione ANAS: %s esiste dopo %s numeri vuoti", target, off - 1)
            # i numeri del buco vanno in ricontrollo (qualcuno potrebbe essere pubblicato dopo)
            lo = max(base + 1, target - MAX_BACKFILL)
            known = self.db.known_ids(lo, target - 1)
            gap = [i for i in range(lo, target) if i not in known]
            self.db.add_missing(gap)
            o = self._store(target, text, advance=True)
            res.fetched += 1
            res.relevant += o.category in RELEVANT
            res.more_pending = True  # riparte subito da qui
            break
        return requests

    def run_cycle(self) -> PollResult:
        res = PollResult()
        cursor = self.db.cursor()
        if cursor is None:
            if self.cfg.anas_start_id is None:
                # normale al primo avvio: il punto di partenza lo fissa l'elenco ufficiale
                log.info("Canale a numeri: aspetto che l'elenco ufficiale fissi il punto di partenza")
                return res
            cursor = self.cfg.anas_start_id - 1
            self.db.set("anas_cursor", str(cursor))
            log.info("Primo avvio: parto da ord_id=%s", self.cfg.anas_start_id)

        budget = self.cfg.max_requests_per_cycle
        try:
            # 1) ricontrollo dei buchi recenti
            for ord_id in self.db.missing_to_recheck(self.cfg.missing_recheck_per_cycle,
                                                     self.cfg.missing_retry_hours):
                if res.requests >= budget:
                    break
                res.requests += 1
                text = self.source.fetch_text(ord_id)
                if text is None:
                    self.db.missing_attempted(ord_id)
                    continue
                o = self._store(ord_id, text, advance=False)
                res.fetched += 1
                res.relevant += o.category in RELEVANT

            # 2) avanzamento oltre il cursore
            ord_id = cursor
            misses: list[int] = []
            while res.requests < budget:
                ord_id += 1
                if self.db.has_ordinanza(ord_id):
                    misses.clear()
                    continue
                res.requests += 1
                text = self.source.fetch_text(ord_id)
                if text is None:
                    misses.append(ord_id)
                    if len(misses) >= self.cfg.max_gap:
                        break
                    continue
                if misses:
                    self.db.add_missing(misses)  # buchi prima di un id esistente
                    misses = []
                o = self._store(ord_id, text, advance=True)
                res.fetched += 1
                res.relevant += o.category in RELEVANT
                self.db.set("anas_last_found_at", str(time.time()))
            else:
                res.more_pending = not misses  # budget esaurito mentre trovavamo ancora roba

            # 3) niente di nuovo da un po'? assaggio più avanti, nel caso di un buco lungo
            if misses and self._lookahead_due() and res.requests < budget:
                res.requests += self._lookahead(res)
        except TransientError as exc:
            res.error = str(exc)
            log.warning("ANAS non raggiungibile, riprovo al prossimo ciclo: %s", exc)
        return res
