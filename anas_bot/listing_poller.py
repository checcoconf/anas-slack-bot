"""Giro sull'elenco ufficiale di Ordinanze Web: la fonte principale delle ordinanze.

Il sito elenca le ordinanze dalla più recente (collaudo del 02/11/2026, 3.718 ordinanze reali),
si rifiuta di elencarne più di 1.000 per ricerca (quindi niente ricerca "tutta Italia": 3.911 in
vigore il 03/11/2026) e il suo firewall mette in quarantena chi fa più di una manciata di richieste
(collaudo del 03/11/2026: bloccati dopo 9 richieste in 27 secondi da un indirizzo, e dopo 6 richieste
in 90 minuti da un altro). Per questo ogni giro fa pochissime richieste, distanziate:

1. LETTURA VELOCE A ROTAZIONE: il giro dura quasi un'ora e fa una richiesta ogni ~4 minuti
   (REQUEST_DELAY_SECONDS): struttura dopo struttura, 1-2 pagine da 5 ciascuna, dalla più recente,
   finché il tempo (JOB_TIME_BUDGET_MINUTES) finisce; il giro dopo riparte dalla prima non letta.
   Si ferma appena una pagina non contiene niente di nuovo; se era ancora tutta nuova, al giro dopo
   quella struttura parte con una pagina in più. I messaggi Slack partono dopo ogni struttura.
   Di notte (LISTING_DEEP_HOURS) legge LISTING_DEEP_PAGES pagine per struttura, allo stesso ritmo:
   il sito ordina per inizio validità, e un'ordinanza nuova può stare in 2ª-4ª pagina.
2. PDF: solo nelle ore della lettura profonda (di notte), al massimo MAX_PDF_PER_RUN per giro: proroghe,
   revoche e province esatte delle chiusure. Di giorno il budget va tutto alle prime pagine, così il giro
   d'Italia dura 2-3 ore: una chiusura nuova parte subito, con la regione della sua struttura (la
   provincia, quando non è nel riepilogo, resta "non determinata"); proroghe e revoche aspettano la notte.
3. BLOCCO: alla prima pagina di blocco del firewall il giro si ferma e il bot non fa richieste
   ad ANAS per BLOCK_PAUSE_MINUTES. Insistere durante la quarantena la allunga soltanto.
4. BUDGET ORARIO: le richieste si contano per ora scorrevole, attraverso i giri (anas/budget.py):
   se l'ora è già piena il giro aspetta o finisce, così due giri accodati non la riempiono due volte.

Niente ordinanze vecchie: alla prima lettura di una struttura le ordinanze trovate vengono solo
segnate come viste (e si fissa l'ID "spartiacque": sotto è tutto vecchio), tranne quelle che
iniziano dal giorno di installazione in poi.

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

from .anas.budget import BudgetExhausted
from .anas.client import BlockedError, TransientError
from .anas.listing import (
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
    requests: int = 0
    seen: int = 0
    new: int = 0
    relevant: int = 0
    silent: int = 0
    upgraded: int = 0
    unknown: dict[str, str] = field(default_factory=dict)  # provvedimento mai visto -> link al PDF
    uncertain: dict[str, str] = field(default_factory=dict)  # chiusura da verificare: motivo -> link al PDF
    max_id: int = 0  # numero più alto visto: tiene vicino al presente il canale a numeri di riserva
    deferred: int = 0  # ordinanze rimandate al giro dopo perché il tetto dei PDF era esaurito
    skipped: list[str] = field(default_factory=list)  # strutture saltate per un errore di rete
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
        self.deep = False  # True nelle ore notturne (LISTING_DEEP_HOURS): più pagine, e i PDF
        self.after_structure = None  # callback senza argomenti: il job manda i messaggi in coda (giro lungo)
        self.watermark = 0  # ID più alto visto al primo giro: sotto è "già in vigore prima del bot"

    def _fetch_text(self, ord_id: int) -> str | None:
        """Testo del PDF, oppure None fuori dalle ore notturne o a tetto dei PDF esaurito (si riprova dopo)."""
        if not self.deep or self.pdf_budget <= 0:
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
            o.uncertain, o.uncertain_why = original.uncertain, original.uncertain_why
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
            if o.category in RELEVANT and not text and self.deep:  # di notte: le province dai destinatari del PDF
                if self.pdf_budget <= 0:
                    res.deferred += 1
                    return  # tetto dei PDF esaurito: la rimandiamo intera al giro dopo
                text = self._fetch_text(ord_id) or ""
                self._enrich_provinces(o, text)
            measures = [m for p in split_provisions(rec.get("RIEPILOGO", "")) for m in p.measures]
            for m in unknown_measures(measures):
                res.unknown.setdefault(m, url)
            if o.uncertain and o.category in RELEVANT:
                res.uncertain.setdefault(o.uncertain_why, url)
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
    def run(self, today: date, deadline: float | None = None, now: float | None = None,
            hour: int | None = None) -> ListingResult:
        """deadline: time.monotonic() oltre il quale non si iniziano altre letture (il resto al giro dopo).
        now: time.time() (sostituibile nei test) per la pausa dopo un blocco del firewall.
        hour: ora locale (0-23) per decidere se è il momento della lettura profonda; None = mai."""
        res = ListingResult()
        clock = time.time if now is None else (lambda: now)  # nei test l'orologio è fermo
        now = clock()
        self.deep = hour is not None and self.cfg.is_deep_hour(hour)
        if self.deep:
            log.info("Elenco: lettura profonda notturna, %d pagine per struttura", self.cfg.listing_deep_pages)
        late = lambda: deadline is not None and time.monotonic() > deadline  # noqa: E731
        self._late = late
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
            self._fast_structures(today, installed, res, late)
        except BudgetExhausted as exc:
            log.info("Elenco: %s", exc)  # non è un errore: il tetto orario ha fatto il suo lavoro
        except BlockedError as exc:
            pause = self.cfg.block_pause_minutes * 60
            self.db.set(BLOCKED_UNTIL, str(clock() + pause))  # da adesso, non dall'inizio del giro
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

    def _fast_structures(self, today: date, installed: str, res: ListingResult, late) -> None:
        """Lettura veloce: LISTING_STRUCTURES_PER_RUN strutture per giro, a rotazione, 1-2 pagine ciascuna.

        Per ogni struttura, alla prima lettura (baseline) legge le pagine massime, segna tutto come già
        visto senza PDF e fissa uno "spartiacque" (ID più alto visto): sotto quello è tutto vecchio.
        Poi si ferma alla prima pagina senza novità. Se l'ultima pagina letta era ancora tutta nuova
        ("carry"), al giro dopo quella struttura parte con una pagina in più."""
        structures = self.structures(today)  # dal menu/elenco noto, in cache per una settimana
        n = len(structures)
        off = int(self.db.get("listing_fast_rr", "0") or 0) % n
        k = min(self.cfg.listing_structures_per_run, n)
        done, streak, failed = 0, 0, []
        try:
            for st in (structures[(off + i) % n] for i in range(k)):
                if late():
                    log.info("Elenco: tempo del giro finito, %s e seguenti al prossimo giro", st.code)
                    break
                try:
                    self._fast_structure(st, today, installed, res)
                except (BlockedError, BudgetExhausted):
                    raise
                except TransientError as exc:
                    # rete o sito in errore su questa struttura: si passa alla successiva; se capita
                    # due volte di fila il sito sta rifiutando tutto e si chiude il giro (riprova all'ora dopo)
                    done += 1
                    streak += 1
                    failed.append(st.code)
                    log.warning("Elenco: struttura %s saltata in questo giro: %s", st.code, exc)
                    if streak >= 3:
                        # tre di fila: il sito (o la rete) non risponde: inutile continuare, riprova all'ora dopo.
                        # Non è un blocco del firewall (quello manda la sua pagina): niente pausa di un'ora.
                        raise TransientError(f"il sito non risponde ({', '.join(failed)}): {exc}") from exc
                    continue
                done += 1
                streak = 0
                if self.after_structure:
                    self.after_structure()  # i messaggi partono subito, non alla fine dell'ora
        finally:
            self.db.set("listing_fast_rr", str((off + done) % n))
            res.skipped = failed

    def _fast_structure(self, st: Structure, today: date, installed: str, res: ListingResult) -> None:
        self.watermark = int(self.db.get(f"listing_watermark_{st.code}", "0") or 0)
        # prima lettura di questa struttura: presa visione (rifatta finché non vede davvero qualcosa)
        baseline = self.db.get(f"listing_done_{st.code}") is None
        carry_key = f"listing_fast_carry_{st.code}"
        carry = 0 if baseline else min(MAX_CARRY_PAGES, int(self.db.get(carry_key, "0") or 0))
        min_pages = max(self.cfg.listing_fast_pages_min, carry + 1)
        if self.deep:
            min_pages = max(min_pages, self.cfg.listing_deep_pages)
        max_pages = max(min_pages, self.cfg.listing_fast_pages_max + carry)
        page, pages, new, max_id = 1, 1, 0, 0
        seen0, new0 = res.seen, res.new
        while page <= min(pages, max_pages):
            if page > 1 and getattr(self, "_late", lambda: False)():
                break  # tempo del giro finito: la prima pagina si legge sempre, le altre al giro dopo (carry)
            body = self.listing.search_page(st.area, today, page, causa=st.causa, causa_dett=st.causa_dett)
            res.requests += 1
            pages = int(body.get("tot_pagine") or 0)
            results = body.get("results") or []
            if page == 1 and not results and int(body.get("tot_record") or 0) > 0:
                raise ListingError(f"la ricerca {st.code} dichiara {body.get('tot_record')} ordinanze ma non le "
                                   f"elenca: {body.get('messaggio') or 'formato cambiato'}")
            ids = [int(r["ID"]) for r in results if str(r.get("ID", "")).isdigit()]
            max_id = max([max_id, *ids])
            new = self._handle_page(results, st, baseline, installed, res)
            if not baseline and page >= min_pages and new == 0:
                break
            page += 1
        seen, found = res.seen - seen0, res.new - new0
        still_new = not baseline and page > max_pages and new > 0 and page <= pages
        log.info("Elenco %s: %d pagine, %d ordinanze viste, %d nuove%s (richieste ad ANAS finora: %d)",
                 st.code, page - 1 if page > max_pages or page > pages else page, seen, found,
                 " (presa visione)" if baseline else "",
                 getattr(getattr(self.listing, "anas", None), "requests_made", 0))
        self.db.set(carry_key, str(max_pages if still_new else 0))
        if baseline:
            # anche una struttura vuota è "vista" (spartiacque 0: la sua prima ordinanza futura è nuova);
            # il caso "il sito dichiara N ordinanze ma non le elenca" è già escluso sopra con ListingError
            self.db.set(f"listing_done_{st.code}", today.isoformat())
            self.db.set(f"listing_watermark_{st.code}", str(max_id))
        res.structures.append(st.code)
