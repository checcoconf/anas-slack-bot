"""Elenco ufficiale di Ordinanze Web: la fonte principale delle ordinanze.

La pagina https://www.stradeanas.it/it/ordinanze-web chiede i risultati con una
richiesta POST a /anas_ordinanzeweb/searchordinanze e riceve un JSON:

    {"esito": true, "tot_pagine": 33, "tot_record": 164,
     "results": [{"ID": "213467", "TIPO_ORDINANZA": "Proroga", "NUMERO_ORDINANZA": "723/2026/BA",
                  "COMPARTIMENTO": "Bari", "CAUSA": "Cantiere", "RIEPILOGO": "<html...>",
                  "PROROGA_DATA": "20/11/2026", ...}, ...]}   # 5 risultati per pagina

Filtrando per "valide da oggi" (data_validita_inizio) si ottengono le ordinanze in
vigore, qualunque sia il loro numero: niente più dipendenza dalla numerazione.

Il RIEPILOGO è un riassunto strutturato dell'atto ("applicata alla tratta SS 16 dal
km ... sulla corsia di marcia attuando i seguenti provvedimenti: <ul><li>...</li></ul>
a partire dal ... fino al ..."): lo classifichiamo direttamente, senza il PDF. Il PDF
serve solo quando il riepilogo è vuoto (proroghe, revoche) e, per le ordinanze utili,
per trovare le province dai destinatari (prefetture, questure).
"""

from __future__ import annotations

import html
import json
import logging
import random
import re
import string
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser

from ..geo import norm
from .client import AnasClient, BlockedError, TransientError, is_block_page
from .robots import ROBOTS_PATH, RobotsPolicy
from .parser import (
    CLOSURE,
    OTHER,
    REOPENING,
    SPEED,
    Ordinanza,
    _nice_title,
    access_kind,
    extract_direction,
    extract_roads,
    regions_from_structure,
)

log = logging.getLogger(__name__)

SITE = "https://www.stradeanas.it"
PAGE_URL = SITE + "/it/ordinanze-web"
ITALY = "*"  # "area_compartimentale" per cercare in tutta Italia, senza scegliere la struttura
MAX_RESULTS = 1000  # il sito mostra al massimo 1.000 risultati per ricerca
SEARCH_URL = SITE + "/anas_ordinanzeweb/searchordinanze"
ROBOTS_URL = SITE + ROBOTS_PATH


# Sigle provate per scoprire le strutture: tutte le province più quelle speciali viste nei numeri
# delle ordinanze (es. 723/2026/BA, 623/2026/UC). Una sigla senza risultati viene ignorata.
CANDIDATE_CODES = (
    "BA", "MI", "FI", "RM", "NA", "TO", "GE", "VE", "BO", "TS", "AN", "PG", "AQ", "CB", "PZ", "CZ", "UC",
    "PA", "CT", "AP", "CA", "SS", "AO", "TN", "BZ", "UD", "VR", "BS", "PD", "FG", "LE", "SA", "RC", "CS",
    "ME", "SR", "AG", "TP", "NU", "OR", "SI", "GR", "AR", "PE", "CH", "TE", "BN", "AV", "CE", "LT", "FR",
    "RI", "VT", "TR", "MC", "PU", "FC", "RA", "PR", "PC", "BL", "SO", "CO", "BG", "AL", "CN", "NO", "TA",
    "BR", "MT", "KR", "VV", "EN", "CL", "RG", "OT", "OG", "VS", "SU",
)


# Strutture ANAS -> regioni coperte (rilevate il 02/11/2026: 23 strutture, 19 regioni).
# Il Trentino-Alto Adige non ha strade ANAS: le gestiscono le Province autonome.
STRUCTURE_REGIONS: dict[str, list[str]] = {
    "AO": ["valle-d-aosta"], "TO": ["piemonte"], "MI": ["lombardia"], "VE": ["veneto"],
    "TS": ["friuli-venezia-giulia"], "GE": ["liguria"], "BO": ["emilia-romagna"], "FI": ["toscana"],
    "PG": ["umbria"], "AN": ["marche"], "RM": ["lazio"], "AQ": ["abruzzo"], "CB": ["molise"],
    "NA": ["campania"], "BA": ["puglia"], "PZ": ["basilicata"], "CZ": ["calabria"],
    "UC": ["basilicata", "calabria", "campania"],  # Autostrada del Mediterraneo (A2)
    "PA": ["sicilia"], "CT": ["sicilia"], "AP": ["sicilia"],  # AP = Autostrade siciliane
    "CA": ["sardegna"], "SS": ["sardegna"],
}


# Le 23 strutture trovate dal collaudo del 02/11/2026 (collaudo/elenco.py). Il menu della pagina è
# costruito dal JavaScript, quindi il bot usa questo elenco invece di provare ogni settimana più di
# 100 sigle. Se ANAS ne aggiunge una, il collaudo la trova e va aggiunta qui.
KNOWN_STRUCTURES: tuple[tuple[str, str], ...] = (
    ("BA", "Bari"), ("MI", "Milano"), ("FI", "Firenze"), ("RM", "Roma"), ("NA", "Napoli"),
    ("TO", "Piemonte"), ("GE", "Genova"), ("VE", "Veneto"), ("BO", "Bologna"), ("TS", "Friuli Venezia Giulia"),
    ("AN", "Ancona"), ("PG", "Perugia"), ("AQ", "Abruzzo"), ("CB", "Molise"), ("PZ", "Potenza"),
    ("CZ", "Catanzaro"), ("UC", "Autostrada del Mediterraneo"), ("PA", "Palermo"), ("CT", "Catania"),
    ("AP", "Autostrade"), ("CA", "Cagliari"), ("SS", "Sassari"), ("AO", "Valle D'Aosta"),
)


class ListingError(Exception):
    """L'elenco non si legge più (formato cambiato o errore del sito)."""


class RelayRejected(ListingError):
    """Il ponte del Worker ha rifiutato la firma del job (HTTP 401 "Firma non valida"): job e Worker hanno
    token Slack diversi, di solito perché i segreti su GitHub sono cambiati e il Worker non è stato ripubblicato.
    ANAS non è stata contattata."""


@dataclass
class Structure:
    """Una struttura territoriale dell'elenco (BA, MI...): il codice è anche la chiave in D1."""
    code: str
    label: str  # nome nel menu, es. "Puglia"
    causa: str = "*"  # filtro "Causa" della ricerca (il valore che manda il sito), "*" = tutte
    causa_dett: str = "*"  # filtro "Dettaglio causa", "*" = tutti

    @property
    def area(self) -> str:
        return self.code


# --- Lettura del menu delle strutture -------------------------------------------

class _SelectParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.selects: list[tuple[dict, list[tuple[str, str]]]] = []
        self._cur: list[tuple[str, str]] | None = None
        self._opt_value: str | None = None
        self._opt_text: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "select":
            self._cur = []
            self.selects.append((a, self._cur))
        elif tag == "option" and self._cur is not None:
            self._opt_value = a.get("value", "")
            self._opt_text = []

    def handle_data(self, data):
        if self._opt_value is not None:
            self._opt_text.append(data)

    def handle_endtag(self, tag):
        if tag == "option" and self._cur is not None and self._opt_value is not None:
            self._cur.append((self._opt_value, " ".join("".join(self._opt_text).split())))
            self._opt_value = None
        elif tag == "select":
            self._cur = None


def parse_structures(page_html: str) -> list[Structure]:
    """Le strutture territoriali dal menu a tendina della pagina (quello che contiene "BA")."""
    p = _SelectParser()
    p.feed(page_html)
    for attrs, options in p.selects:
        name = (attrs.get("name", "") + attrs.get("id", "")).lower()
        values = {v for v, _ in options}
        if "compart" in name or "struttur" in name or "BA" in values:
            return [Structure(v, t) for v, t in options if v and v not in ("*", "All", "_none")]
    return []


# --- Client ---------------------------------------------------------------------

def describe_error_page(page: str, limit: int = 400) -> str:
    """Titolo e testo visibile di una pagina di errore, per capire chi la manda (sito o firewall)."""
    title = re.search(r"<title[^>]*>(.*?)</title>", page or "", re.I | re.S)
    body = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", page or "")
    text = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", body)).split())
    head = f"titolo «{' '.join(title.group(1).split())}» " if title else ""
    return f"{head}testo «{text[:limit]}»"


class ListingClient:
    """Interroga l'elenco usando la stessa sessione (cookie, User-Agent, pause) dei PDF."""

    def __init__(self, anas: AnasClient) -> None:
        self.anas = anas
        self.session = anas.session
        self._primed = False
        self.last_total_records = 0

    def _get(self, url: str):
        self.anas._throttle(url.rsplit("/", 1)[-1] or url)
        try:
            return self.session.get(url, timeout=self.anas.timeout)
        except Exception as exc:  # noqa: BLE001 - rete: riprovare al prossimo giro
            raise TransientError(f"pagina Ordinanze Web: {exc}") from exc

    # Il cookie di sessione che il sito assegna aprendo la pagina viene conservato nel database tra un giro
    # e l'altro: così la pagina iniziale (1 richiesta su 10) non si rilegge ogni ora. Se il cookie non vale
    # più, la ricerca risponde 500 e la pagina si riapre da sola (vedi search_page).
    COOKIES_KEY = "anas_cookies"

    def restore_cookies(self, db) -> bool:
        """Rimette nella sessione i cookie dell'ultimo giro; True se ce n'erano."""
        try:
            saved = json.loads(db.get(self.COOKIES_KEY, "") or "{}")
        except ValueError:
            saved = {}
        if not isinstance(saved, dict) or not saved:
            return False
        for name, value in saved.items():
            self.session.cookies.set(name, value, domain="www.stradeanas.it")
        self._primed = True
        log.info("Cookie di sessione ripresi dal giro precedente: pagina iniziale non riletta")
        return True

    def save_cookies(self, db) -> None:
        jar = {c.name: c.value for c in self.session.cookies if "stradeanas" in (c.domain or "")}
        if jar:
            db.set(self.COOKIES_KEY, json.dumps(jar))

    def load_robots(self) -> RobotsPolicy:
        """Legge /robots.txt e imposta la policy condivisa (anche i PDF la rispettano).

        Sito in errore 5xx (anche il blocco del firewall lo è): per prudenza non interroghiamo nulla.
        robots.txt assente (404): nessuna regola, tutto permesso.
        """
        ua = self.anas.user_agent
        try:
            r = self._get(ROBOTS_URL)
        except TransientError as exc:
            log.warning("robots.txt non raggiungibile (%s): per prudenza non interrogo ANAS in questo giro", exc)
            self.anas.robots = RobotsPolicy.disallow_all(ua)
            return self.anas.robots
        if is_block_page(r.text):
            self.anas.robots = RobotsPolicy.disallow_all(ua)
            raise BlockedError(f"firewall ANAS: robots.txt bloccato (HTTP {r.status_code})")
        if r.status_code == 200:
            policy = RobotsPolicy.from_text(r.text, ua)
            vietati = [u for u in (PAGE_URL, SEARCH_URL) if not policy.allowed(u)]
            if vietati:
                log.warning("robots.txt di ANAS ora vieta: %s — rispetto il divieto e non le interrogo",
                            ", ".join(vietati))
            else:
                log.info("robots.txt letto: le pagine delle ordinanze sono consentite (crawl-delay %ss)",
                         policy.crawl_delay() or "nessuno")
        elif r.status_code >= 500:
            log.warning("robots.txt: HTTP %s (sito in errore o bloccato): non interrogo ANAS in questo giro",
                        r.status_code)
            policy = RobotsPolicy.disallow_all(ua)
        else:
            log.info("robots.txt non presente (HTTP %s): nessuna restrizione dichiarata", r.status_code)
            policy = RobotsPolicy.from_text("", ua)  # text="" = letto dal sito, vuoto: si può mettere in cache
        self.anas.robots = policy
        return policy

    def prime(self) -> str:
        """Apre la pagina come un visitatore: il sito imposta il cookie di sessione."""
        if not self.anas.robots.allowed(PAGE_URL):
            raise TransientError("robots.txt vieta /it/ordinanze-web: non interrogo il sito")
        r = self._get(PAGE_URL)
        if r.headers.get("x-relay-colo"):
            log.info("Pagina Ordinanze Web letta dal ponte del Worker (ingresso %s, esecuzione %s)",
                     r.headers["x-relay-colo"], r.headers.get("cf-placement", "non indicata"))
        if r.status_code != 200:
            log.warning("Pagina Ordinanze Web: HTTP %s: %s", r.status_code, describe_error_page(r.text))
        if is_block_page(r.text):
            raise BlockedError(f"firewall ANAS: pagina Ordinanze Web bloccata (HTTP {r.status_code})")
        if r.status_code != 200:
            raise TransientError(f"pagina Ordinanze Web: HTTP {r.status_code}")
        self._primed = True  # solo a pagina letta davvero: altrimenti la ricerca la riapre (cookie di sessione)
        self.last_page_html = r.text
        return r.text

    def structures(self, day: date | None = None) -> list[Structure]:
        """Le strutture territoriali: dal menu della pagina se c'è, altrimenti scoperte interrogando la ricerca."""
        found = parse_structures(self.prime())
        return found or [Structure(c, label) for c, label in KNOWN_STRUCTURES]

    def discover_structures(self, day: date, progress=None, retries: int = 0) -> list[Structure]:
        """Il menu viene riempito dal JavaScript: proviamo le sigle possibili (tutte le province più
        le sigle speciali viste nei numeri delle ordinanze) e teniamo quelle con risultati.

        progress(i, n, code, struttura_o_None, totale) viene chiamato dopo ogni sigla provata."""
        found = []
        for i, code in enumerate(CANDIDATE_CODES, 1):
            body = self._with_retries(lambda: self.search_page(code, day, 1), retries)
            total = int(body.get("tot_record") or 0)
            st = None
            if total > 0:
                label = (body.get("results") or [{}])[0].get("COMPARTIMENTO", code)
                st = Structure(code, label)
                found.append(st)
            if progress:
                progress(i, len(CANDIDATE_CODES), code, st, total)
        if not found:
            raise ListingError("nessuna struttura territoriale trovata: la ricerca non risponde come previsto")
        return found

    def total_italy(self, day: date) -> int:
        """Ordinanze in vigore in tutta Italia (per controllare di non aver dimenticato strutture)."""
        return int(self.search_page("*", day, 1).get("tot_record") or 0)

    def search_page(self, code: str, day: date, page: int, causa: str = "*", causa_dett: str = "*") -> dict:
        if not self.anas.robots.allowed(SEARCH_URL):
            raise TransientError("robots.txt vieta la ricerca delle ordinanze: non interrogo il sito")
        if not self._primed:
            self.prime()
        self.anas._throttle(f"ricerca {code} pagina {page}")
        data = {
            "action": "search_ordinanze", "page": str(page), "causa": causa or "*", "causa_dett": causa_dett or "*",
            "area_compartimentale": code, "strada": "*", "numero_ordinanza": "", "limitazioni": "*",
            "data_validita_inizio": day.isoformat(), "data_validita_fine": "",
            "random": "".join(random.choices(string.ascii_letters, k=5)),
        }
        headers = {"Accept": "application/json, text/javascript, */*; q=0.01",
                   "X-Requested-With": "XMLHttpRequest", "Origin": "https://www.stradeanas.it",
                   "Referer": PAGE_URL}
        for attempt in (1, 2):
            try:
                r = self.session.post(SEARCH_URL, data=data, headers=headers, timeout=self.anas.timeout)
            except Exception as exc:  # noqa: BLE001 - rete: riprovare al prossimo giro
                raise TransientError(f"elenco: {exc}") from exc
            if is_block_page(r.text):
                # quarantena del firewall, con qualunque codice HTTP: riprovare la allungherebbe soltanto
                log.warning("Elenco %s pagina %s: %s", code, page, describe_error_page(r.text, 200))
                raise BlockedError(f"firewall ANAS: ricerca {code} bloccata (HTTP {r.status_code})")
            if r.status_code < 500 or attempt == 2:
                break
            # il sito a volte risponde 500: riapro la pagina (cookie nuovi) e riprovo una volta
            log.warning("Elenco %s pagina %s: HTTP %s: %s. Riprovo", code, page, r.status_code,
                        describe_error_page(r.text))
            self.prime()
            self.anas._throttle(f"ricerca {code} pagina {page} (secondo tentativo)")
        if r.status_code in (429, 500, 502, 503, 504):
            raise TransientError(f"elenco {code}: HTTP {r.status_code}")
        if r.status_code == 401 and "Firma non valida" in (r.text or ""):
            raise RelayRejected("il ponte del Worker ha rifiutato la firma del job (HTTP 401): il Worker ha un token "
                                "Slack diverso da quello del job. Ripubblica il Worker (Actions -> Pubblica Worker "
                                "(Cloudflare)). ANAS non è stata contattata, nessuna richiesta consumata")
        try:
            body = r.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise ListingError(f"elenco: risposta non JSON (HTTP {r.status_code})") from exc
        if not isinstance(body, dict) or "results" not in body:
            raise ListingError("elenco: formato della risposta cambiato")
        return body

    def iter_structure(self, code: str, day: date, max_pages: int = 250, on_page=None, retries: int = 0):
        """Tutti i risultati di una struttura, pagina dopo pagina.

        on_page(pagina, pagine_totali, ordinanze_totali) viene chiamato dopo ogni pagina."""
        page, total = 1, 1
        while page <= min(total, max_pages):
            body = self._with_retries(lambda: self.search_page(code, day, page), retries)
            total = int(body.get("tot_pagine") or 0)
            self.last_total_records = int(body.get("tot_record") or 0)
            if on_page:
                on_page(page, total, self.last_total_records)
            yield from body.get("results") or []
            page += 1

    on_retry = None  # on_retry(tentativo, massimo, attesa_secondi, errore): per mostrare i nuovi tentativi

    def _with_retries(self, call, retries: int):
        import time
        for attempt in range(retries + 1):
            try:
                return call()
            except BlockedError:
                raise  # quarantena del firewall: riprovare la allunga soltanto
            except TransientError as exc:
                if attempt == retries:
                    raise
                wait = 30 * (attempt + 1)
                if self.on_retry:
                    self.on_retry(attempt + 1, retries, wait, exc)
                time.sleep(wait)


# --- Classificazione dal RIEPILOGO ----------------------------------------------

_TRATTA_SPLIT = re.compile(r"applicata alla tratta", re.IGNORECASE)
_LI = re.compile(r"<li[^>]*>(.*?)</li>", re.IGNORECASE | re.DOTALL)
_TAGS = re.compile(r"<[^>]+>")
_DATE = r"(\d{1,2})/(\d{1,2})/(\d{4})"
_START = re.compile(r"a partire dal\s+" + _DATE)
_END = re.compile(r"fino al\s+" + _DATE)
_WINDOW = re.compile(r"fascia oraria dalle\s+(\d{1,2})[:.](\d{2})\s+alle\s+(\d{1,2})[:.](\d{2})")
_KM_RANGE = re.compile(r"dal km\s*(\d{1,4}\+\d{3})\s*al km\s*(\d{1,4}\+\d{3})")
_KM_ONE = re.compile(r"\bal km\s*(\d{1,4}\+\d{3})")
_ROAD_NAME = re.compile(r"^\s*(?:ss|sp|sr|nsa|ra|a)\s*\d+\s*(?:bis|ter|dir|var|racc)?\s*(.*?)\s*(?:dal km|al km|$)")
_SPEED = re.compile(r"limite (?:massimo )?di velocita\s*(\d{2,3})\s*km")

# --- Regole, ricavate dal vocabolario reale di ANAS (collaudo del 02/11/2026: 3.718 ordinanze,
# 77 voci di provvedimento, vedi anas_bot/anas/vocabolario.py e collaudo/LEGGIMI.md) ---------------

# Provvedimenti che chiudono la strada (se valgono per tutti gli utenti).
CLOSING_MEASURES = ("chiusura al traffico", "divieto di transito", "interdizione", "sospensione della circolazione",
                    # il traffico di questa carreggiata passa sull'altra: questa non si percorre (regola Waze, 05/11/2026)
                    "deviazione del traffico su carreggiata opposta", "spostamento su carreggiata opposta")
OPENING_MEASURES = ("apertura al traffico", "riapertura")
# Il provvedimento lascia passare il traffico: non è una chiusura per Waze.
PASSING_MEASURES = ("senso unico alternato",)

# Dove vale il provvedimento (testo tra i km e "attuando").
_WHOLE = re.compile(
    r"tutte le corsie|intera carreggiata|intera sede|entrambe le carreggiate|tutta la sede"
    r"|chiusura (?:totale )?(?:della|delle|di una|di entrambe le) carreggiat|carreggiata [a-z]+ chiusa"
)
# accessi e strade di servizio: chiusi loro, ma la strada principale no. "complanare"/"controstrada": in Waze
# sono segmenti a sé (758/2026/BA, SS 16 km 810: chiusa la complanare per la zona commerciale, la SS 16 aperta)
RAMPS = ("rampa", "svincolo", "area di servizio", "stazione di servizio", "complanare", "controstrada")
LANES = ("corsia di marcia", "corsia di sorpasso", "corsia di emergenza", "corsia di accelerazione",
         "corsia di decelerazione", "corsia preferenziale", "corsia di destra", "corsia di sinistra",
         "corsia destra", "corsia sinistra", "banchina",
         # parti a lato della strada che in Waze non sono segmenti (ordinanza reale su SS 18 VAR, 03/11/2026)
         "piazzola di sosta", "piazzola", "area di sosta", "area di parcheggio", "parcheggio")
# Il "dove" di una chiusura (testo tra i km e "attuando") che il bot sa interpretare. Se dopo "su/sulla/
# nella/lungo…" c'è una dicitura che non contiene nessuna di queste parole, la chiusura parte lo stesso ma
# "da verificare", e la dicitura arriva in admin: è così che il vocabolario cresce senza rileggere i PDF.
KNOWN_WHERE = ("corsi", "carreggiat", "sede stradale", "sede viabile", "rampa", "svincolo", "direzion", "senso",
               "entrambe", "area di servizio", "stazione di servizio", "tratt", "strada", "piazzola", "area di sosta",
               "parcheggio", "banchina", "galleria", "viadotto", "ponte", "rotatoria", "intersezione", "incrocio",
               "complanare", "controstrada", "cavalcavia", "sottopasso", "bretella")
_WHERE_PHRASE = re.compile(r"\b(?:su|sulla|sulle|sul|sui|sugli|nella|nelle|nel|nei|lungo|in)\s+([^,;]{3,60})")

# Diciture che indicano chiusure parziali o a fasi alterne: il traffico continua a passare.
PARTIAL_HINTS = ("chiusura della corsia", "chiusura delle corsie", "chiusura della sola corsia",
                 "chiusura alternata", "a fasi alterne", "fasi alternate", "restringimento")
# Queste diciture dicono che il traffico passa comunque, anche se c'è scritto "tutte le corsie".
ALWAYS_PASSING_HINTS = ("senso unico alternato", "corsia libera", "garantendo la circolazione", "a vista")
# Chiusure brevi per il passaggio di un trasporto eccezionale: inutili per la mappa.
IGNORED_CLOSURE_CAUSES = ("trasporto eccezionale",)

# Limiti di velocità "permanenti": senza data di fine e per queste cause (non cantieri, frane, trasporti).
PERMANENT_SPEED_CAUSES = ("regolamentazione della circolazione", "apertura nuova strada", "tratto pericoloso")

# Utenti: chiusura "per tutti" oppure solo per alcune categorie (mezzi pesanti, pedoni...)?
_RESTRICTED = re.compile(
    r"massa|altezza|larghezza|lunghezza|peso|merci|eccezional|autocarr|autoarticolat|autotren"
    r"|rimorchio|esplosiv|infiammabil|pedoni|velocipedi|ciclomotori|motocicl|macchine agricole"
    r"|trazione animale|trattori|motocarrozzette|autobus"
)


# Categorie di utenti che ANAS elenca dopo "tutti gli utenti" quando il divieto è solo per loro
# (riclassificazione a strada tipo B, 05/11/2026, SS 719: "tutti gli utenti, veicoli a trazione animale,
# velocipedi, veicoli a braccia, macchine agricole, ciclomotori, motocicli"): le auto passano.
_CATEGORY_LIST = re.compile(r"velociped|biciclett|a braccia|trazione animale|macchine agricole|ciclomotor|motocicl"
                            r"|motocarrozz|pedon|animali|autocarr|autoarticolat|autotren|autobus|mezzi pesanti"
                            r"|massa superiore|veicoli aventi massa")


def everyone(users: str) -> bool:
    """True se il provvedimento riguarda le auto normali.

    "tutti gli utenti", "tutti gli autoveicoli", "tutti", "tutti tranne mezzi di soccorso",
    "tutti tranne traffico locale" -> sì; "tutti veicoli aventi massa superiore a 44t",
    "autocarri", "pedoni ; velocipedi" -> no. "tutti gli utenti, velocipedi, veicoli a braccia, ..." -> no:
    è l'elenco delle categorie a cui si applica il divieto. Con più gruppi separati da ";" basta che uno valga
    per tutti.
    """
    users = users.split("l'ordinanza sara")[0]
    for group in (g.strip(" ;,.") for g in users.split(";")):
        if not group:
            continue
        if group.startswith("tutti gli utenti"):
            rest = group[len("tutti gli utenti"):].strip(" ,")
            if rest and not rest.startswith(("tranne", "eccetto", "ad eccezione", "esclus")) and _CATEGORY_LIST.search(rest):
                continue  # "tutti gli utenti" seguito dalle categorie: vale solo per quelle
            return True
        if group.startswith("tutti tranne") or group in ("tutti", "tutti gli autoveicoli", "autovetture"):
            return True
        if group.startswith("tutti") and not _RESTRICTED.search(group):
            return True
    return False


def _plain(fragment: str) -> str:
    text = _TAGS.sub(" ", fragment.replace("<li>", "; ").replace("<br>", " "))
    return " ".join(html.unescape(text).replace(" ", " ").split())


def _iso(d: str, m: str, y: str) -> str:
    try:
        return date(int(y), int(m), int(d)).isoformat()
    except ValueError:
        return ""


@dataclass
class Provision:
    """Una tratta del riepilogo, con i suoi provvedimenti."""
    text: str  # testo semplice normalizzato (minuscolo, senza accenti)
    plain: str  # testo semplice leggibile
    measures: list[str]  # voci dell'elenco "provvedimenti", normalizzate
    lanes: str  # parte tra i km e "attuando": quali corsie/rampe
    category: str = OTHER
    ramp_only: bool = False
    where_unknown: str = ""  # dicitura del "dove" mai vista (chiusura da verificare)


def unknown_where(lanes: str) -> str:
    """La prima dicitura del "dove" (dopo su/sulla/nella/lungo…) senza nessuna parola nota, oppure ""."""
    after_km = re.split(r"al km\s*\d{1,4}\+\d{3}|dal km\s*\d{1,4}\+\d{3}", lanes)[-1]
    for m in _WHERE_PHRASE.finditer(after_km):
        phrase = m.group(1).strip()
        if not any(k in phrase for k in KNOWN_WHERE):
            return phrase
    return ""


def split_provisions(riepilogo_html: str) -> list[Provision]:
    raw = html.unescape(riepilogo_html or "")
    parts = [p for p in _TRATTA_SPLIT.split(raw)[1:] if p.strip()] or ([raw] if raw.strip() else [])
    out = []
    for part in parts:
        plain = _plain(part)
        text = norm(plain)
        measures = [norm(_plain(m)) for m in _LI.findall(part)]
        before = text.split("attuando")[0]
        out.append(Provision(text=text, plain=plain, measures=measures, lanes=before))
    return out


def classify_provision(p: Provision, rec: dict | None = None) -> Provision:
    """Classifica una tratta del riepilogo usando le voci fisse dei provvedimenti."""
    rec = rec or {}
    users = p.text.split("interessera:")[-1] if "interessera:" in p.text else "tutti gli utenti"
    for_all = everyone(users)
    measures = p.measures
    closing = [m for m in measures if m.startswith(CLOSING_MEASURES)]
    opening = [m for m in measures if m.startswith(OPENING_MEASURES)]
    passing = any(m.startswith(PASSING_MEASURES) for m in measures)

    detail = norm(rec.get("CAUSA_DETT", ""))
    ignored = any(c in detail for c in IGNORED_CLOSURE_CAUSES) or any("trasporto eccezionale" in m for m in measures)
    if closing and for_all and not passing and not ignored and not any(h in p.lanes for h in ALWAYS_PASSING_HINTS):
        whole = bool(_WHOLE.search(p.lanes))
        ramp = any(r in p.lanes for r in RAMPS)
        lanes_only = any(lane in p.lanes for lane in LANES) and not whole and not ramp
        # "restringimento carreggiata" tra i provvedimenti: la "chiusura al traffico" accanto è di una corsia,
        # non della strada né dello svincolo: il traffico passa (749/2026/BA, SS 7 svincolo per la A14, 10/11/2026:
        # le tavole del PDF erano "chiusura della corsia di emergenza" e "chiusura della corsia di marcia")
        narrowed = any(m.startswith("restringimento") for m in measures)
        partial = (any(h in p.lanes for h in PARTIAL_HINTS) or narrowed) and not whole
        if not lanes_only and not partial:
            p.category = CLOSURE
            p.ramp_only = ramp and not whole
            if not whole and not ramp:
                p.where_unknown = unknown_where(p.lanes)
            return p
    if opening and for_all and not closing:
        p.category = REOPENING
        return p
    speed = [m for m in measures if _SPEED.search(m)]
    # il limite di velocità vale per tutti anche quando il divieto accanto è per alcune categorie
    # ("tutti gli utenti, velocipedi, ..."): basta che "tutti gli utenti" compaia
    speed_for_all = for_all or "tutti gli utenti" in users
    if speed and speed_for_all and not _END.search(p.text):
        if (any(c in detail for c in PERMANENT_SPEED_CAUSES) or "permanent" in p.text
                or "classificazione" in p.text or "tipo b" in p.text or "tipo a" in p.text):
            p.category = SPEED  # riclassificazione della strada: limite nuovo, definitivo
    return p


def record_to_ordinanza(rec: dict, structure_label: str, pdf_url: str) -> Ordinanza | None:
    """Ordinanza classificata dal riepilogo, oppure None se il riepilogo è vuoto (serve il PDF)."""
    ord_id = int(rec["ID"])
    provisions = [classify_provision(p, rec) for p in split_provisions(rec.get("RIEPILOGO", ""))]
    if not provisions:
        return None
    category, chosen = OTHER, provisions[0]
    for wanted in (CLOSURE, SPEED, REOPENING):
        hit = next((p for p in provisions if p.category == wanted), None)
        if hit:
            category, chosen = wanted, hit
            break

    o = Ordinanza(ord_id=ord_id, category=category, pdf_url=pdf_url)
    apply_record_fields(o, rec, structure_label)
    o.roads, names = extract_roads(chosen.text)
    road_name = _ROAD_NAME.search(chosen.text)
    if o.roads and road_name and road_name.group(1):
        o.road_names = {o.roads[0]: _nice_title(road_name.group(1).strip(" -,"))}
    else:
        o.road_names = {k: v for k, v in names.items() if k in o.roads}
    km = _KM_RANGE.search(chosen.text)
    if km:
        o.km_from, o.km_to = km.group(1), km.group(2)
    elif (k1 := _KM_ONE.search(chosen.text)):
        o.km_from = k1.group(1)
    if (m := _START.search(chosen.text)):
        o.start_date = _iso(*m.groups())
    if (m := _END.search(chosen.text)):
        o.end_date = _iso(*m.groups())
    o.open_ended = not o.end_date
    if (m := _WINDOW.search(chosen.text)):
        h1, m1, h2, m2 = m.groups()
        o.time_window = f"{int(h1):02d}:{m1}-{int(h2):02d}:{m2}"
    if category == SPEED:
        values = [int(m.group(1)) for x in chosen.measures for m in [_SPEED.search(x)] if m]
        o.speeds = sorted(set(values))
        o.speed_kmh = values[0] if values else None
    if category == REOPENING and "apertura nuova strada" in norm(rec.get("CAUSA_DETT", "")):
        o.new_road = True
    if category == CLOSURE:
        closures = [p for p in provisions if p.category == CLOSURE]
        o.ramp_only = all(p.ramp_only for p in closures)
        if o.ramp_only:
            o.access_kind = access_kind(" ".join(p.lanes for p in closures))
    # la direzione si cerca nel "dove" e nel resto del testo, ma non nell'elenco dei provvedimenti:
    # "restringimento carreggiata destra" non è il senso di marcia
    rest = chosen.text
    for m in chosen.measures:
        rest = rest.replace(m, " ")
    o.direction = extract_direction(chosen.lanes) or extract_direction(rest)
    o.excerpt = clean_excerpt(chosen.plain)
    if category == CLOSURE and chosen.where_unknown:
        o.uncertain = True
        o.uncertain_why = f"dicitura mai vista nel \"dove\": «{chosen.where_unknown}»"
    o.listing_record = {k: v for k, v in rec.items() if k != "RIEPILOGO"} | {"RIEPILOGO": rec.get("RIEPILOGO", "")}
    return o


def clean_excerpt(plain: str) -> str:
    """Il riepilogo come frase leggibile: senza premesse, senza la lista dei destinatari."""
    t = re.sub(r"^\s*l'ordinanza sar[aà] applicata alle seguenti tratte:\s*", "", plain, flags=re.I)
    t = re.split(r"\binteresser[aà]\b", t, maxsplit=1, flags=re.I)[0]
    t = re.sub(r"\s*attuando i seguenti provvedimenti:\s*[;,]?\s*", " → ", t, flags=re.I)
    t = re.sub(r"\s+([,;.])", r"\1", " ".join(t.split()))
    return t.strip(" ;,")[:350]


def apply_record_fields(o: Ordinanza, rec: dict, structure_label: str) -> None:
    """Campi che l'elenco dà sempre: numero, struttura, regioni, proroga."""
    o.number = (rec.get("NUMERO_ORDINANZA") or "").replace("\\/", "/") or o.number
    o.structure = rec.get("COMPARTIMENTO") or o.structure
    if not o.regions or not o.provinces:
        sigla = o.number.rsplit("/", 1)[-1].upper() if o.number.count("/") == 2 else ""
        regions = (STRUCTURE_REGIONS.get(sigla) or regions_from_structure(structure_label)
                   or regions_from_structure(o.structure, sigla))
        if regions and not o.provinces:
            o.regions = regions
            o.province_inferred = False
    if "proroga" in norm(rec.get("TIPO_ORDINANZA", "")):
        o.extension = True
        m = re.match(_DATE, rec.get("PROROGA_DATA") or "")
        if m:
            o.end_date = _iso(*m.groups())
            o.open_ended = False
