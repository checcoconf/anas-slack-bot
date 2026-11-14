"""Lettura del testo di un'ordinanza ANAS e classificazione.

Il testo arriva dal PDF (vedi pdftext.py). Qui decidiamo:
- che tipo di provvedimento è: chiusura, riapertura, limite di velocità
  permanente, oppure "altro" (lavori, corsie, sensi unici alternati...);
- su quali strade, tratti chilometrici, province e regioni;
- in che periodo e in che fascia oraria vale.

Il lavoro avviene sulla sezione "ORDINA" dell'atto, cioè le disposizioni vere
e proprie. Ogni disposizione (di solito un punto elenco) viene valutata da
sola: un'ordinanza con una corsia chiusa E una rampa chiusa conta come
chiusura, una con sole corsie chiuse no.

Tutte le liste di parole chiave stanno in cima al file: se ANAS usa formule
diverse da quelle previste, si correggono qui senza toccare la logica.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date

from ..geo import PROVINCE_BY_CODE, PROVINCES, find_provinces, find_regions, norm

PARSER_VERSION = 1

CLOSURE = "chiusura"
REOPENING = "riapertura"
SPEED = "limite_velocita"
OTHER = "altro"
UNREADABLE = "illeggibile"

# --- Parole chiave (testo già normalizzato: minuscolo, senza accenti) -------

CLOSURE_PHRASES = (
    "chiusura al traffico",
    "chiusura al transito",
    "chiusura totale",
    "chiusa al traffico",
    "chiuso al traffico",
    "chiusa al transito",
    "chiuso al transito",
    "interdizione al traffico",
    "interdizione del traffico",
    "interdizione al transito",
    "sospensione della circolazione",
    "sospensione del traffico",
    "divieto di transito a tutti",
    "divieto di transito per tutti",
    "chiusura della carreggiata",
    "chiusura della rampa",
    "chiusura delle rampe",
    "chiusura dello svincolo",
    "chiusura della galleria",
    "chiusura del tratto",
    "chiusura della tratta",
    "chiusura della strada",
    "chiusura dell'intera",
)

# Se una disposizione contiene una di queste, NON è una chiusura per Waze
# (la strada resta percorribile, almeno in parte).
PARTIAL_PHRASES = (
    "chiusura della corsia",
    "chiusura delle corsie",
    "chiusura corsia",
    "corsie: corsia",
    "corsia di marcia",
    "corsia di sorpasso",
    "corsia di emergenza",
    "corsia di accelerazione",
    "corsia di decelerazione",
    "restringimento",
    "senso unico alternato",
    "doppio senso di circolazione",
    "scambio di carreggiata",
    "parzializzazione",
    "riduzione della carreggiata",
    "banchina",
    # parti a lato della strada che in Waze non sono segmenti: chiuderle non ferma il traffico
    # (ordinanza reale SS 18 VAR, 03/11/2026). Le aree di servizio NO: in Waze hanno rampe e vanno segnalate.
    "piazzola di sosta",
    "piazzola",
    "area di sosta",
    "area di parcheggio",
    "piazzale di sosta",
)

# Accessi laterali: la chiusura si segnala come "svincolo chiuso" (o rampa, o area di servizio), la strada resta aperta.
ACCESS_PHRASES = ("rampa", "svincolo", "area di servizio", "stazione di servizio")
_ACCESS_KINDS = (("area di servizio", "area di servizio"), ("stazione di servizio", "area di servizio"),
                 ("svincolo", "svincolo"), ("rampa", "rampa"), ("complanare", "complanare"),
                 ("controstrada", "controstrada"))


def access_kind(text: str) -> str:
    """Quali accessi chiude il testo (normalizzato): "svincolo", "rampa", "area di servizio", o combinazioni."""
    kinds: list[str] = []
    for phrase, kind in _ACCESS_KINDS:
        if phrase in text and kind not in kinds:
            kinds.append(kind)
    return " e ".join(kinds)

# Divieti che valgono solo per alcune categorie di veicoli.
VEHICLE_RESTRICTION_PHRASES = (
    "veicoli di massa",
    "massa complessiva",
    "mezzi pesanti",
    "veicoli pesanti",
    "trasporti eccezionali",
    "trasporto eccezionale",
    "veicoli adibiti al trasporto di merci",
    "autoarticolati",
)
ALL_USERS_PHRASES = (
    "tutti gli utenti",
    "tutti i veicoli",
    "tutte le categorie di veicoli",
    "qualsiasi veicolo",
)

REOPENING_PHRASES = (
    "riapertura al traffico",
    "riapertura al transito",
    "riapertura della",
    "riapertura dello",
    "riapertura del",
    "revoca della chiusura",
    "revoca dell'ordinanza di chiusura",
    "ripristino della circolazione",
)

_WHOLE_CARRIAGEWAY = re.compile(
    r"chiusura (?:al traffico |totale )?(?:della|dell'intera|di una|delle) carreggiat[ae]|carreggiata [a-z]+ chiusa"
    r"|tutte le corsie|intera carreggiata|intera sede|entrambe le carreggiate|tutta la sede|intero tratto|intera tratta"
)
_REVOKE_CLOSURE = re.compile(r"\brevoca\b[^;]{0,120}?\bchiusur[ae]\b")

SPEED_RE = re.compile(r"limite (?:massimo )?di velocita[^.;]{0,80}?(\d{2,3})\s*km\s*/?\s*h")
PERMANENT_PHRASES = (
    "permanente",
    "in via definitiva",
    "definitivamente",
    "a tempo indeterminato",
    "carattere definitivo",
)
TEMPORARY_PHRASES = (
    "cantiere",
    "durata dei lavori",
    "termine dei lavori",
    "fine lavori",
    "provvisori",
    "temporane",
)

# --- Estrattori -------------------------------------------------------------

_DATE_NUM = re.compile(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})\b")
_MONTHS = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6,
    "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}
_DATE_TXT = re.compile(r"\b(\d{1,2})\s+(" + "|".join(_MONTHS) + r")\s+(\d{4})\b")
_OPEN_ENDED = re.compile(
    r"fino a (?:nuova disposizione|nuovo provvedimento|revoca)|fino al termine dei lavori|fino a fine lavori"
)
_TIME_WINDOW = re.compile(
    r"dalle(?: ore)?\s*(\d{1,2})[:.](\d{2})\s*(?:alle|fino alle)(?: ore)?\s*(\d{1,2})[:.](\d{2})"
)
_KM_RANGE = re.compile(r"dal km\.?\s*(\d{1,4}\s?\+\s?\d{3})\s*al km\.?\s*(\d{1,4}\s?\+\s?\d{3})")
_KM_SINGLE = re.compile(r"\bal km\.?\s*(\d{1,4}\s?\+\s?\d{3})")
# "ORDINANZA N°723/2026/BA", "Ordinanza n. 128/2024", "ordinanza n.107 2019 UC"
_NUMBER = re.compile(r"ordinanza\s*n\s*[°º.o]?\s*(\d{1,5})\s*(?:/\s*|\s)(\d{4})(?:\s*/\s*([a-z]{2,3})\b)?")
_EXTENSION = re.compile(r"\bprorog")
# "proroga dell'ordinanza n. 459", "vista l'ordinanza n. ...": numeri di ALTRE ordinanze, non di questa
_CITED_BEFORE = re.compile(r"(?:dell['’ ]?|della |citata |vista |vist[ae] l['’ ]?|n\. ?)\s*$")


def _own_number(head: str):
    """Il numero di questa ordinanza: salta quelli citati (proroghe e revoche citano l'originale per primo)."""
    matches = list(_NUMBER.finditer(head))
    for m in matches:
        if not _CITED_BEFORE.search(head[max(0, m.start() - 15):m.start()]):
            return m
    return matches[0] if matches else None
_ST = re.compile(
    r"(?:struttura|coordinamento|area compartimentale)\s+territoriale\s+(.{3,60}?)"
    r"(?=\s+(?:via|viale|piazza|corso|contrada|largo|localita|t \[|tel|pec)\b|$)"
)

_ROAD_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:strada statale|s\.\s?s\.|ss)\s*n?\.?\s*(\d{1,3})(\s?(?:bis|ter|dir|var|racc)\b)?"), "SS"),
    (re.compile(r"\b(?:nuova strada anas|n\.?s\.?a\.?|nsa)\s*(\d{1,4})\b"), "NSA"),
    (re.compile(r"\b(?:raccordo autostradale|r\.a\.)\s*n?\.?\s*(\d{1,2})\b"), "RA"),
    (re.compile(r"\bautostrada\s+a\s?(\d{1,2})\b"), "A"),
    (re.compile(r"\ba(\d{1,2})\b(?!\s*km)"), "A"),
)
_BOTH_DIRECTIONS = re.compile(
    r"entramb[ei] (?:le |i )?(?:direzioni|sensi di marcia|sensi|carreggiate)|ambo i sensi|ambedue le direzioni"
)
# "in direzione Roma", ", direzione Sondrio", "carreggiata nord - direzione Siena" (testi reali di ANAS)
_TOWARDS = re.compile(
    r"(?:\bin\s+|[,\-]\s*|\bcarreggiata\s+\w+\s+)direzione\s+(?:di\s+)?([a-z' ./\-]{3,40}?)"
    r"(?=\s*[,;.]|\s(?:dal|al|a partire|dalle|nella|per|con|e|tra|attuando|verso)\b|\s*$)"
)
_NOT_A_PLACE = ("crescente", "decrescente", "da ", "opposta", "nord", "sud", "est", "ovest")
_CARRIAGEWAY = re.compile(r"carreggiata (nord|sud|est|ovest|destra|sinistra)\b")
_ROAD_NAME = re.compile(r"strada statale\s*n?\.?\s*(\d{1,3})\s*\"([^\"]{3,50})\"")


@dataclass
class Ordinanza:
    ord_id: int
    category: str
    pdf_url: str = ""
    number: str = ""
    structure: str = ""
    roads: list[str] = field(default_factory=list)
    road_names: dict[str, str] = field(default_factory=dict)
    km_from: str = ""
    km_to: str = ""
    provinces: list[str] = field(default_factory=list)
    regions: list[str] = field(default_factory=list)
    province_inferred: bool = True  # False se le regioni vengono solo dalla Struttura Territoriale
    start_date: str = ""  # ISO yyyy-mm-dd
    end_date: str = ""  # ISO, vuoto se "fino a nuova disposizione"
    open_ended: bool = False
    time_window: str = ""  # es. "22:00-06:00"
    speed_kmh: int | None = None
    ramp_only: bool = False
    access_kind: str = ""  # se ramp_only: cosa chiude, es. "svincolo", "rampa", "area di servizio", "svincolo e rampa"
    extension: bool = False  # proroga di una chiusura già in vigore
    new_road: bool = False  # apertura di una strada/svincolo/carreggiata nuova
    speeds: list[int] = field(default_factory=list)  # tutti i limiti dell'ordinanza, es. [30, 50, 70]
    direction: str = ""  # "entrambe le direzioni", "verso Pescara", "carreggiata Nord"
    excerpt: str = ""
    parser_version: int = PARSER_VERSION
    # Classificazione non sicura: l'avviso parte lo stesso, con l'etichetta "da verificare", e la dicitura
    # nuova arriva in admin. Così una dicitura mai vista non viene né scartata né data per certa.
    uncertain: bool = False
    uncertain_why: str = ""
    listing_record: dict = field(default_factory=dict)  # il risultato grezzo dell'elenco, per rileggere a posteriori

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def motorway(self) -> bool:
        """Riguarda un'autostrada o un raccordo autostradale (codici A2, A19, RA6...)."""
        return any(r.startswith("A") or r.startswith("RA") for r in self.roads)

    def is_expired(self, today: date) -> bool:
        if not self.end_date or self.open_ended:
            return False
        return date.fromisoformat(self.end_date) < today


def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(p in text for p in phrases)


def _first_index(text: str, phrases: tuple[str, ...]) -> int | None:
    idx = [i for i in (text.find(p) for p in phrases) if i >= 0]
    return min(idx) if idx else None


def ordina_section(text: str) -> str:
    """Restituisce il dispositivo dell'atto (dopo 'ORDINA'), o tutto il testo se non lo trova."""
    m = re.search(r"\bO\s?R\s?D\s?I\s?N\s?A\b", text)
    if not m:
        m = re.search(r"\b(?:ordina|dispone)\s*:", text, flags=re.IGNORECASE)
    if not m:
        return text
    rest = text[m.end():]
    end = re.search(
        r"\b(?:DISPONE|AVVERTE|DEMANDA|INFORMA|Avverso il presente|La presente ordinanza|"
        r"Il Responsabile|IL RESPONSABILE|Il Dirigente|IL DIRIGENTE)\b",
        rest,
    )
    return rest[: end.start()] if end else rest


def split_provisions(section: str) -> list[str]:
    """Spezza il dispositivo in singole disposizioni (punti elenco, numeri, lettere)."""
    flat = re.sub(r"\s+", " ", section)
    parts = re.split(r"(?:^|\s)(?:\*|•|▪|►|-\s(?=[A-Za-z])|\d{1,2}\)|[a-z]\))\s+", flat)
    parts = [p.strip(" ;") for p in parts if len(p.strip()) > 15]
    return parts or [flat.strip()]


def classify_provision(p: str) -> str:
    """Classifica una singola disposizione (testo normalizzato)."""
    # "revoca dell'ordinanza n. 480/2026 di chiusura al traffico" -> riapertura
    if _REVOKE_CLOSURE.search(p):
        return REOPENING
    # "riapertura al traffico della SS..." -> riapertura;
    # "chiusura al traffico ... con riapertura alle 6" -> resta una chiusura.
    reo = _first_index(p, REOPENING_PHRASES)
    clo = _first_index(p, CLOSURE_PHRASES)
    if reo is not None and (clo is None or reo < clo):
        return REOPENING
    if _contains_any(p, CLOSURE_PHRASES):
        if _contains_any(p, PARTIAL_PHRASES):
            return OTHER
        if _contains_any(p, VEHICLE_RESTRICTION_PHRASES) and not _contains_any(p, ALL_USERS_PHRASES):
            return OTHER
        return CLOSURE
    if SPEED_RE.search(p):
        if _contains_any(p, PERMANENT_PHRASES) and not _contains_any(p, TEMPORARY_PHRASES):
            return SPEED
    return OTHER


def _iso(d: int, m: int, y: int) -> str | None:
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return None


def extract_dates(section_norm: str) -> list[str]:
    found: list[str] = []
    for d, m, y in _DATE_NUM.findall(section_norm):
        iso = _iso(int(d), int(m), int(y))
        if iso:
            found.append(iso)
    for d, mon, y in _DATE_TXT.findall(section_norm):
        iso = _iso(int(d), _MONTHS[mon], int(y))
        if iso:
            found.append(iso)
    return sorted(set(found))


def extract_roads(text_norm: str) -> tuple[list[str], dict[str, str]]:
    roads: list[str] = []
    for rx, prefix in _ROAD_PATTERNS:
        for m in rx.finditer(text_norm):
            num = m.group(1)
            suffix = (m.group(2) or "").strip().upper() if rx.groups > 1 else ""
            code = f"{prefix}{num}{' ' + suffix if suffix else ''}"
            if code not in roads:
                roads.append(code)
    names = {f"SS{n}": _nice_title(name.strip()) for n, name in _ROAD_NAME.findall(text_norm)}
    return roads, names


_SMALL_WORDS = {"e", "di", "del", "della", "dello", "dei", "degli", "delle", "da", "dal", "al", "in", "per"}


def _nice_title(s: str) -> str:
    """"abruzzo e molise" -> "Abruzzo e Molise"; "della maielletta" -> "della Maielletta"."""
    words = s.split()
    return " ".join(w if w in _SMALL_WORDS else w[:1].upper() + w[1:] for w in words)


def regions_from_structure(structure: str, sigla: str = "") -> list[str]:
    """Regione dalla Struttura Territoriale ("Abruzzo e Molise", "Bari") o dalla sigla nel numero ("/BA")."""
    if structure:
        found = find_regions(structure)
        if found:
            return found
        s = norm(structure)
        found = sorted({p.region for p in PROVINCES
                        if any(re.search(rf"\b{re.escape(a)}\b", s) for a in p.aliases)})
        if found:
            return found
    if sigla in PROVINCE_BY_CODE:
        return [PROVINCE_BY_CODE[sigla].region]
    return []


def extract_direction(text_norm: str) -> str:
    if _BOTH_DIRECTIONS.search(text_norm):
        return "entrambe le direzioni"
    m = _TOWARDS.search(text_norm)
    if m and not m.group(1).startswith(_NOT_A_PLACE):
        return "verso " + _nice_title(m.group(1).strip(" .-"))
    m = _CARRIAGEWAY.search(text_norm)
    if m:
        return "carreggiata " + m.group(1).capitalize()
    return ""


def _km(s: str) -> str:
    return s.replace(" ", "")


def parse_ordinanza(ord_id: int, text: str, pdf_url: str = "") -> Ordinanza:
    """Trasforma il testo grezzo di un'ordinanza in un oggetto Ordinanza classificato."""
    if len(text.strip()) < 80:
        return Ordinanza(ord_id=ord_id, category=UNREADABLE, pdf_url=pdf_url)

    full = norm(text)
    section_raw = ordina_section(text)
    section = norm(section_raw)
    provisions = split_provisions(section_raw)
    kinds = [(classify_provision(norm(p)), p) for p in provisions]

    # Priorità: chiusura > limite permanente > riapertura > altro
    category = OTHER
    chosen = ""
    for wanted in (CLOSURE, SPEED, REOPENING):
        hit = next((p for k, p in kinds if k == wanted), None)
        if hit:
            category, chosen = wanted, hit
            break

    o = Ordinanza(ord_id=ord_id, category=category, pdf_url=pdf_url)

    m = _own_number(full[:5000])
    sigla = ""
    if m:
        sigla = (m.group(3) or "").upper()
        o.number = f"{m.group(1)}/{m.group(2)}" + (f"/{sigla}" if sigla else "")
    m = _ST.search(full[:3000])
    if m:
        o.structure = _nice_title(m.group(1).strip(" -,."))

    roads_source = norm(chosen) if chosen else section
    o.roads, names = extract_roads(roads_source)
    if not o.roads:
        o.roads, names = extract_roads(full)
    o.road_names = {k: v for k, v in names.items() if k in o.roads}

    chosen_n = norm(chosen) if chosen else section
    km = _KM_RANGE.search(chosen_n)
    if km:
        o.km_from, o.km_to = _km(km.group(1)), _km(km.group(2))
    else:
        km1 = _KM_SINGLE.search(chosen_n)
        if km1:
            o.km_from = _km(km1.group(1))

    if category == CLOSURE:
        closures = [norm(p) for k, p in kinds if k == CLOSURE]
        o.ramp_only = all(any(a in c for a in ACCESS_PHRASES) and not _WHOLE_CARRIAGEWAY.search(c)
                          for c in closures)
        if o.ramp_only:
            o.access_kind = access_kind(" ".join(closures))
        if not o.ramp_only and not any(_WHOLE_CARRIAGEWAY.search(c) for c in closures):
            # dal testo libero del PDF, senza "intera carreggiata"/"tutte le corsie": può essere una parte
            # della strada che il bot non conosce (il 03/11/2026 era una piazzola di sosta)
            o.uncertain = True
            o.uncertain_why = "chiusura letta dal testo del PDF, senza indicazione esplicita dell'intera carreggiata"
        o.extension = bool(_EXTENSION.search(norm(chosen)) or _EXTENSION.search(section))

    if category == SPEED:
        sm = SPEED_RE.search(chosen_n)
        o.speed_kmh = int(sm.group(1)) if sm else None

    # Province: prima il dispositivo, poi tutto l'atto (destinatari: prefetture, questure...)
    provs = find_provinces(section) or find_provinces(full)
    o.provinces = provs
    if provs:
        o.regions = sorted({PROVINCE_BY_CODE[p].region for p in provs})
    else:
        o.province_inferred = False
        o.regions = regions_from_structure(o.structure, sigla)
        if "autostrada del mediterraneo" in full and not o.regions:
            o.regions = ["basilicata", "calabria", "campania"]

    dates = extract_dates(section)
    if dates:
        o.start_date, o.end_date = dates[0], dates[-1]
        if len(dates) == 1:
            o.end_date = ""  # una sola data: è l'inizio, la fine non è nota
    o.open_ended = bool(_OPEN_ENDED.search(section)) or (bool(o.start_date) and not o.end_date)

    tw = _TIME_WINDOW.search(chosen_n) or _TIME_WINDOW.search(section)
    if tw:
        h1, m1, h2, m2 = tw.groups()
        o.time_window = f"{int(h1):02d}:{m1}-{int(h2):02d}:{m2}"

    o.direction = extract_direction(chosen_n)
    o.excerpt = re.sub(r"\s+", " ", chosen).strip()[:350]
    return o
