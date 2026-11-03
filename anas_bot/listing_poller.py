"""Giro sull'elenco ufficiale di Ordinanze Web: la fonte principale delle ordinanze.

Il sito elenca le ordinanze dalla più recente (collaudo del 02/11/2026, 3.718 ordinanze reali)
e il suo firewall mette in quarantena chi fa più di una manciata di richieste in poco tempo
(collaudo del 03/11/2026: bloccati alla 9ª richiesta in 27 secondi). Per questo ogni giro fa
pochissime richieste, distanziate:

1. LETTURA VELOCE "TUTTA ITALIA": una sola ricerca senza struttura (area "*"), ordinata dalla
   più recente, 1-2 pagine da 5. Si ferma appena una pagina non contiene niente di nuovo.
   Se l'ultima pagina letta era ancora tutta nuova, al giro dopo legge una pagina in più.
2. PDF: al massimo MAX_PDF_PER_RUN per giro (proroghe, revoche, province delle chiusure);
   le ordinanze che ne hanno bisogno oltre il tetto restano "nuove" e slittano al giro dopo.
3. BLOCCO: alla prima pagina di blocco del firewall il giro si ferma e il bot non fa richieste
   ad ANAS per BLOCK_PAUSE_MINUTES. Insistere durante la quarantena la allunga soltanto.
4. LETTURA COMPLETA a rotazione (una struttura per intero): disponibile ma spenta
   (LISTING_FULL_PER_RUN=0), costa decine di richieste.

Niente ordinanze vecchie: al primo giro le ordinanze trovate vengono solo segnate come viste,
tranne quelle che iniziano dal giorno di installazione in poi.

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

from .anas.client import BlockedError, TransientError
from .anas.listing import (
    ITALY,
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
from .poller import BLOCKED_UNTIL  # chiave in D1: time.time() fino a cui non si interroga ANAS

log = logging.getLogger(__name__)

_REF_NUMBER = re.compile(r"\b(\d{1,5})\s*/\s*(\d{4})\s*/\s*([A-Z]{2,3})\b")
MAX_CARRY_PAGES = 6  # pagine in più che la lettura veloce può accumulare se arrivano molte novità
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
    deferred: int = 0  # ordinanze rimandate al giro dopo perché il tetto dei PDF era esaurito
    error: str = ""
    broken: bool = False  # il formato dell'elenco è cambiato
    blocked: bool = False  # il firewall ci ha bloccati (o siamo ancora in pausa dopo un blocco)
    block_started: bool = False  # il blocco è scattato in questo giro (per l'avviso in admin)


class ListingPoller:
    def __init__(self, db: Database, listing: ListingClient, source, cfg: Config) -> None:
        self.db = db
        self.listing = listing
        self.source = source  # PdfSource: per proroghe/revoche e per trovare le province
        self.cfg = cfg
        self.pdf_budget = cfg.max_pdf_per_run  # PDF ancora scaricabili in questo giro
        self.watermark = 0  # ID più alto visto al primo giro: sotto è "già in vigore prima del bot"

    def _fetch_text(self, ord_id: int) -> str | None:
        """Testo del PDF, oppure None se il tetto dei PDF per giro è esaurito (si riprova al giro dopo)."""
        if self.pdf_budget <= 0:
            return None
        self.pdf_budget -= 1
        return self.source.fetch_text(ord_id)

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
        text = self._fetch_text(ord_id)
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
        # "vecchia": trovata al primo giro, oppure più in basso di tutto ciò che il primo giro aveva visto
        # (gli ID crescono con la pubblicazione): si segna come vista, salvo che inizi dopo l'installazione
        old = baseline or (self.watermark and ord_id <= self.watermark)
        if o is None:
            if old:  # già in vigore prima del bot: si segna come vista senza scaricare il PDF
                o = Ordinanza(ord_id=ord_id, category=OTHER, pdf_url=url, parser_version=UNREAD)
                apply_record_fields(o, rec, st.label)
                self.db.save_ordinanza(o, "", silent=True)
                res.new += 1
                res.silent += 1
                return
            o, text = self._from_pdf(rec, st)
            if o is None:
                res.deferred += 1
                return  # PDF non ancora pubblicato, o tetto dei PDF esaurito: riprova al giro dopo
        silent = bool(old) and not (o.start_date and o.start_date >= installed)
        if not silent:
            if o.category in RELEVANT and not text:  # utile: le province dai destinatari del PDF
                if self.pdf_budget <= 0:
                    res.deferred += 1
                    return  # tetto dei PDF esaurito: la rimandiamo intera al giro dopo
                text = self._fetch_text(ord_id) or ""
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
            rst = self._record_structure(rec) if st.code == ITALY else st
            if ord_id in known:
                if not baseline:  # il canale a numeri l'aveva scartata? l'elenco può correggerla
                    o = record_to_ordinanza(rec, rst.label, self.source.url_for(ord_id))
                    if o and o.category in RELEVANT and self.db.upgrade_from_listing(o):
                        res.upgraded += 1
                continue
            new += 1
            self._process(rec, rst, baseline, installed, res)
        return new

    @staticmethod
    def _record_structure(rec: dict) -> Structure:
        """La struttura di un risultato della ricerca "tutta Italia": sigla dal numero (723/2026/BA),
        nome dal campo COMPARTIMENTO."""
        number = (rec.get("NUMERO_ORDINANZA") or "").replace("\\/", "/")
        code = number.rsplit("/", 1)[-1].upper() if number.count("/") == 2 else ""
        return Structure(code or ITALY, rec.get("COMPARTIMENTO") or "Italia")

    # --- il giro --------------------------------------------------------------------
    def run(self, today: date, deadline: float | None = None, now: float | None = None) -> ListingResult:
        """deadline: time.monotonic() oltre il quale non si iniziano altre letture (il resto al giro dopo).
        now: time.time() (sostituibile nei test) per la pausa dopo un blocco del firewall."""
        res = ListingResult()
        now = time.time() if now is None else now
        late = lambda: deadline is not None and time.monotonic() > deadline  # noqa: E731
        installed = self.db.get("installed_on")
        if not installed:
            installed = today.isoformat()
            self.db.set("installed_on", installed)

        # In pausa dopo un blocco del firewall: nessuna richiesta ad ANAS finché non scade
        blocked_until = float(self.db.get(BLOCKED_UNTIL, "0") or 0)
        if blocked_until > now:
            res.blocked = True
            res.error = f"in pausa dopo un blocco del firewall ANAS, riprendo tra {int((blocked_until - now) / 60) + 1} min"
            log.warning("Elenco: %s", res.error)
            return res

        self.pdf_budget = self.cfg.max_pdf_per_run
        try:
            self._fast_italy(today, installed, res)
            if self.cfg.listing_full_per_run > 0 and not late():
                self._full_rotation(today, installed, res)
        except BlockedError as exc:
            pause = self.cfg.block_pause_minutes * 60
            self.db.set(BLOCKED_UNTIL, str(now + pause))
            res.error, res.blocked, res.block_started = str(exc), True, True
            log.warning("Elenco: %s. Nessuna richiesta ad ANAS per %d minuti", exc, self.cfg.block_pause_minutes)
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

    def _fast_italy(self, today: date, installed: str, res: ListingResult) -> None:
        """Lettura veloce: la ricerca "tutta Italia", dalla più recente, poche pagine.

        Al primo giro (baseline) legge le pagine massime e segna tutto come già visto, senza PDF.
        Poi si ferma alla prima pagina senza novità. Se l'ultima pagina letta era ancora tutta
        nuova ("carry"), al giro dopo legge almeno una pagina in più: le ordinanze oltre il
        limite non vanno perse."""
        st = Structure(ITALY, "Italia")
        baseline = self.db.get("listing_done_italia") is None
        self.watermark = int(self.db.get("listing_watermark_id", "0") or 0)
        carry = 0 if baseline else min(MAX_CARRY_PAGES, int(self.db.get("listing_fast_carry", "0") or 0))
        min_pages = max(self.cfg.listing_fast_pages_min, carry + 1)
        max_pages = max(min_pages, self.cfg.listing_fast_pages_max + carry)
        page, pages, new = 1, 1, 0
        while page <= min(pages, max_pages):
            body = self.listing.search_page(ITALY, today, page)
            res.requests += 1
            pages = int(body.get("tot_pagine") or 0)
            new = self._handle_page(body.get("results") or [], st, baseline, installed, res)
            if not baseline and page >= min_pages and new == 0:
                break
            page += 1
        still_new = not baseline and page > max_pages and new > 0 and page <= pages
        self.db.set("listing_fast_carry", str(max_pages if still_new else 0))
        if baseline:
            self.db.set("listing_done_italia", today.isoformat())
            self.db.set("listing_watermark_id", str(res.max_id))
        res.structures.append(ITALY)

    def _full_rotation(self, today: date, installed: str, res: ListingResult) -> None:
        """Lettura completa di una struttura a rotazione (rete di sicurezza, spenta di default:
        una struttura sono 30-60 richieste). Un turno ogni LISTING_FULL_EVERY_RUNS giri."""
        tick = int(self.db.get("listing_full_tick", "0") or 0)
        self.db.set("listing_full_tick", str(tick + 1))
        if tick % self.cfg.listing_full_every_runs != 0:
            return
        structures = self.structures(today)
        for st in self._next_full(structures):
            baseline = self.db.get(f"listing_done_{st.code}") is None
            records = list(self.listing.iter_structure(st.code, today))
            res.requests += max(1, (len(records) + 4) // 5)
            if getattr(self.listing, "last_total_records", 0) >= MAX_RESULTS:
                raise ListingError(f"la struttura {st.code} supera i {MAX_RESULTS} risultati: "
                                   "l'elenco sarebbe incompleto, serve dividere la ricerca")
            self._handle_page(records, st, baseline, installed, res)
            self.db.set(f"listing_done_{st.code}", today.isoformat())
            self._advance_full(structures)
            res.full.append(st.code)
