"""Giro sull'elenco ufficiale di Ordinanze Web: la fonte principale delle ordinanze.

Il collaudo del 02/11/2026 (3.718 ordinanze reali) ha mostrato che il sito elenca le
ordinanze dalla più recente: in tutte le strutture le 10 più nuove stanno nelle prime
2-4 pagine. Per questo a ogni giro:

1. LETTURA VELOCE: per ognuna delle 23 strutture legge le prime pagine e si ferma appena
   una pagina non contiene niente di nuovo (minimo 2, massimo 6 pagine). Così ogni
   ordinanza nuova arriva entro un giro (15 minuti), qualunque numero abbia.
2. LETTURA COMPLETA a rotazione (una struttura per giro): rete di sicurezza per le
   ordinanze che il sito non mettesse in cima.

Niente ordinanze vecchie: finché una struttura non è stata letta per intero la prima volta,
le ordinanze trovate vengono solo segnate come viste, tranne quelle che iniziano dal giorno
di installazione in poi.

Proroghe e revoche non hanno riepilogo nell'elenco: si legge il PDF e, se cita un'ordinanza
già vista dal bot, ne eredita strada, km e tipo (una proroga di una chiusura resta una chiusura).
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date

from .anas.client import TransientError
from .anas.listing import (
    MAX_RESULTS,
    ListingClient,
    ListingError,
    Structure,
    apply_record_fields,
    record_to_ordinanza,
    split_provisions,
)
from .anas.parser import CLOSURE, OTHER, REOPENING, Ordinanza, parse_ordinanza
from .anas.vocabolario import unknown_measures
from .config import Config
from .db import RELEVANT, Database
from .geo import PROVINCE_BY_CODE, find_provinces, norm

log = logging.getLogger(__name__)

_REF_NUMBER = re.compile(r"\b(\d{1,5})\s*/\s*(\d{4})\s*/\s*([A-Z]{2,3})\b")
STUCK_AFTER_RUNS = 12  # 3 ore
UNREAD = 0  # parser_version delle ordinanze segnate come viste senza leggerne il PDF
_INHERITED = ("category", "roads", "road_names", "km_from", "km_to", "provinces", "regions", "province_inferred",
              "start_date", "time_window", "speed_kmh", "speeds", "ramp_only", "new_road", "direction", "excerpt")


@dataclass
class ListingResult:
    structures: list[str] = field(default_factory=list)
    full: list[str] = field(default_factory=list)
    requests: int = 0
    seen: int = 0
    new: int = 0
    relevant: int = 0
    silent: int = 0
    upgraded: int = 0
    unknown: dict[str, str] = field(default_factory=dict)  # provvedimento mai visto -> link al PDF
    max_id: int = 0  # numero più alto visto: tiene vicino al presente il canale a numeri di riserva
    skipped: list[str] = field(default_factory=list)  # strutture non lette in questo giro
    stuck: list[str] = field(default_factory=list)    # strutture in errore da 12 giri di fila (3 ore)
    error: str = ""
    broken: bool = False  # il formato dell'elenco è cambiato


class ListingPoller:
    def __init__(self, db: Database, listing: ListingClient, source, cfg: Config) -> None:
        self.db = db
        self.listing = listing
        self.source = source  # PdfSource: per proroghe/revoche e per trovare le province
        self.cfg = cfg

    # --- strutture, riscoperte una volta a settimana ----------------------------
    def structures(self, today: date) -> list[Structure]:
        cached = self.db.get("listing_structures")
        day = self.db.get("listing_structures_day") or ""
        if cached and day and (today - date.fromisoformat(day)).days < 7:
            return [Structure(**s) for s in json.loads(cached)]
        found = self.listing.structures(today)
        self.db.set("listing_structures", json.dumps([s.__dict__ for s in found], ensure_ascii=False))
        self.db.set("listing_structures_day", today.isoformat())
        log.info("Strutture territoriali nell'elenco: %s", ", ".join(s.code for s in found))
        return found

    def _next_full(self, structures: list[Structure]) -> list[Structure]:
        """Le prossime strutture da leggere per intero (il turno avanza solo quando la lettura riesce)."""
        n = max(0, min(self.cfg.listing_full_per_run, len(structures)))
        start = int(self.db.get("listing_rr", "0") or 0) % len(structures)
        return [structures[(start + i) % len(structures)] for i in range(n)]

    def _advance_full(self, structures: list[Structure]) -> None:
        start = int(self.db.get("listing_rr", "0") or 0)
        self.db.set("listing_rr", str((start + 1) % len(structures)))

    # --- costruzione di un'ordinanza ----------------------------------------------
    @staticmethod
    def _enrich_provinces(o: Ordinanza, text: str) -> None:
        provs = find_provinces(text)
        if provs:
            o.provinces = provs
            o.regions = sorted({PROVINCE_BY_CODE[p].region for p in provs})
            o.province_inferred = True

    def _from_pdf(self, rec: dict, st: Structure) -> tuple[Ordinanza | None, str]:
        """Proroghe, revoche e ordinanze senza riepilogo: PDF + eventuale ordinanza originale citata."""
        ord_id = int(rec["ID"])
        url = self.source.url_for(ord_id)
        text = self.source.fetch_text(ord_id)
        if text is None:
            return None, ""
        own = (rec.get("NUMERO_ORDINANZA") or "").replace("\\/", "/").upper()
        refs = [f"{a}/{b}/{c}" for a, b, c in _REF_NUMBER.findall(text.upper())]
        original = next((self.db.find_by_number(r) for r in refs if r != own and self.db.find_by_number(r)), None)
        tipo = norm(rec.get("TIPO_ORDINANZA", ""))
        # Un'ordinanza originale già classificata decide il tipo, anche se è "altro": la proroga di un
        # restringimento resta un restringimento (verificato sulla proroga reale 621/2026/UC -> 459/2026/UC).
        # Fanno eccezione le ordinanze segnate durante l'installazione senza leggerle (UNREAD).
        if original is not None and (original.category in RELEVANT or original.parser_version != UNREAD):
            o = Ordinanza(ord_id=ord_id, category=original.category, pdf_url=url)
            for name in _INHERITED:
                setattr(o, name, getattr(original, name))
            if "revoca" in tipo:
                o.category = REOPENING if original.category == CLOSURE else OTHER
                o.end_date, o.open_ended = "", True
            apply_record_fields(o, rec, st.label)
            if "revoca" not in tipo and not o.end_date:
                o.end_date = original.end_date
            return o, text
        o = parse_ordinanza(ord_id, text, url)
        apply_record_fields(o, rec, st.label)
        self._enrich_provinces(o, text)
        return o, text

    def _process(self, rec: dict, st: Structure, baseline: bool, installed: str, res: ListingResult) -> None:
        ord_id = int(rec["ID"])
        url = self.source.url_for(ord_id)
        o = record_to_ordinanza(rec, st.label, url)
        text = ""
        if o is None:
            if baseline:  # già in vigore prima del bot: si segna come vista senza scaricare il PDF
                o = Ordinanza(ord_id=ord_id, category=OTHER, pdf_url=url, parser_version=UNREAD)
                apply_record_fields(o, rec, st.label)
                self.db.save_ordinanza(o, "", silent=True)
                res.new += 1
                res.silent += 1
                return
            o, text = self._from_pdf(rec, st)
            if o is None:
                return  # PDF non ancora pubblicato: riprova alla prossima lettura
        silent = baseline and not (o.start_date and o.start_date >= installed)
        if not silent:
            if o.category in RELEVANT and not text:  # utile: le province dai destinatari del PDF
                text = self.source.fetch_text(ord_id) or ""
                self._enrich_provinces(o, text)
            measures = [m for p in split_provisions(rec.get("RIEPILOGO", "")) for m in p.measures]
            for m in unknown_measures(measures):
                res.unknown.setdefault(m, url)
            self.db.set("anas_last_found_at", str(time.time()))
        self.db.save_ordinanza(o, text, silent=silent)
        res.new += 1
        res.silent += silent
        res.relevant += (o.category in RELEVANT) and not silent

    def _handle_page(self, records: list[dict], st: Structure, baseline: bool, installed: str,
                     res: ListingResult) -> int:
        """Elabora una pagina; restituisce quante ordinanze nuove conteneva."""
        records = [r for r in records if str(r.get("ID", "")).isdigit()]
        ids = [int(r["ID"]) for r in records]
        known = self.db.known_among(ids)
        res.seen += len(ids)
        res.max_id = max([res.max_id, *ids])
        new = 0
        for rec in records:
            ord_id = int(rec["ID"])
            if ord_id in known:
                if not baseline:  # il canale a numeri l'aveva scartata? l'elenco può correggerla
                    o = record_to_ordinanza(rec, st.label, self.source.url_for(ord_id))
                    if o and o.category in RELEVANT and self.db.upgrade_from_listing(o):
                        res.upgraded += 1
                continue
            new += 1
            self._process(rec, st, baseline, installed, res)
        return new

    # --- il giro --------------------------------------------------------------------
    def run(self, today: date, deadline: float | None = None) -> ListingResult:
        """deadline: time.monotonic() oltre il quale non si iniziano altre strutture (il resto al giro dopo)."""
        res = ListingResult()
        late = lambda: deadline is not None and time.monotonic() > deadline  # noqa: E731
        installed = self.db.get("installed_on")
        if not installed:
            installed = today.isoformat()
            self.db.set("installed_on", installed)
        try:
            structures = self.structures(today)
            failed: list[str] = []
            # 1) lettura veloce delle prime pagine di tutte le strutture
            # se un giro finisce il tempo, il successivo riparte dalla prima struttura non letta
            off = int(self.db.get("listing_fast_rr", "0") or 0) % max(1, len(structures))
            streak = 0
            for i, st in enumerate(structures[off:] + structures[:off]):
                if late():
                    log.warning("Elenco: tempo del giro finito, %s e seguenti al prossimo giro", st.code)
                    self.db.set("listing_fast_rr", str((off + i) % len(structures)))
                    break
                baseline = self.db.get(f"listing_done_{st.code}") is None
                # durante l'installazione è tutto "nuovo": bastano le pagine minime, il resto lo fa la rotazione
                max_pages = self.cfg.listing_fast_pages_min if baseline else self.cfg.listing_fast_pages_max
                page, pages = 1, 1
                try:
                    while page <= min(pages, max_pages):
                        body = self.listing.search_page(st.code, today, page)
                        res.requests += 1
                        pages = int(body.get("tot_pagine") or 0)
                        new = self._handle_page(body.get("results") or [], st, baseline, installed, res)
                        if page >= self.cfg.listing_fast_pages_min and new == 0:
                            break
                        page += 1
                except TransientError as exc:  # una struttura in errore non ferma le altre
                    failed.append(st.code)
                    streak += 1
                    log.warning("Elenco: struttura %s saltata in questo giro: %s", st.code, exc)
                    if streak >= 3:  # il sito sta rifiutando tutto: inutile insistere, si riprova al giro dopo
                        log.warning("Elenco: 3 strutture di fila in errore, mi fermo e riprovo al prossimo giro")
                        self.db.set("listing_fast_rr", str((off + i + 1) % len(structures)))
                        raise TransientError(f"il sito risponde con errori ({', '.join(failed)})") from exc
                    continue
                streak = 0
                res.structures.append(st.code)
            if structures and len(failed) == len(structures):
                raise TransientError(f"nessuna struttura leggibile ({', '.join(failed)})")
            # 2) lettura completa di una struttura a rotazione: a ogni giro durante l'installazione,
            #    poi un giro ogni LISTING_FULL_EVERY_RUNS (per pesare poco sul sito ANAS)
            installing = any(self.db.get(f"listing_done_{s.code}") is None for s in structures)
            tick = int(self.db.get("listing_full_tick", "0") or 0)
            self.db.set("listing_full_tick", str(tick + 1))
            due = installing or tick % self.cfg.listing_full_every_runs == 0
            for st in [] if late() or not due else self._next_full(structures):
                baseline = self.db.get(f"listing_done_{st.code}") is None
                try:
                    records = list(self.listing.iter_structure(st.code, today))
                except TransientError as exc:
                    log.warning("Elenco: lettura completa di %s rimandata al prossimo giro: %s", st.code, exc)
                    continue
                res.requests += max(1, (len(records) + 4) // 5)
                if getattr(self.listing, "last_total_records", 0) >= MAX_RESULTS:
                    raise ListingError(f"la struttura {st.code} supera i {MAX_RESULTS} risultati: "
                                       "l'elenco sarebbe incompleto, serve dividere la ricerca")
                self._handle_page(records, st, baseline, installed, res)
                self.db.set(f"listing_done_{st.code}", today.isoformat())
                self._advance_full(structures)
                res.full.append(st.code)
            for st in structures:
                key = f"listing_fail_{st.code}"
                if st.code in failed:
                    n = int(self.db.get(key, "0") or 0) + 1
                    self.db.set(key, str(n))
                    if n == STUCK_AFTER_RUNS:
                        res.stuck.append(st.code)
                elif self.db.get(key) not in (None, "0"):
                    self.db.set(key, "0")
            res.skipped = failed
        except TransientError as exc:
            res.error = str(exc)
            log.warning("Elenco ANAS non raggiungibile, riprovo al prossimo giro: %s", exc)
        except ListingError as exc:
            res.error, res.broken = str(exc), True
            log.error("Elenco ANAS non leggibile: %s", exc)
        # Il canale a numeri (di riserva) riparte sempre da qui: se un giorno l'elenco non si legge,
        # cerca solo le ordinanze più nuove, mai quelle vecchie di mesi.
        if res.max_id > (self.db.cursor() or 0):
            self.db.set("anas_cursor", str(res.max_id))
        return res
