"""Regioni e province italiane (assetto al 1° novembre 2026).

Serve a due cose:
1. costruire i menu a tendina di Slack (regioni, e province raggruppate per regione);
2. riconoscere le province citate nel testo di un'ordinanza ANAS
   (es. "PREFETTURA DI CHIETI", "in provincia di Foggia").

Sardegna: dal riordino della L.R. 7/2021 le province sono 8 (CA e SS città
metropolitane, NU, OR, OT, OG, VS, SU). "Sud Sardegna" non esiste più: se
compare in un testo vecchio la mappiamo su SU e VS.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Zona speciale scelta come una regione: tutte le autostrade e i raccordi autostradali (A*, RA*) d'Italia,
# qualunque sia la regione. Non è una regione geografica: nessuna provincia le appartiene.
MOTORWAYS = "autostrade"
MOTORWAYS_LABEL = "🛣️ Autostrade (tutta Italia)"

REGIONS: dict[str, str] = {
    # codice interno -> nome mostrato
    "abruzzo": "Abruzzo",
    "basilicata": "Basilicata",
    "calabria": "Calabria",
    "campania": "Campania",
    "emilia-romagna": "Emilia-Romagna",
    "friuli-venezia-giulia": "Friuli-Venezia Giulia",
    "lazio": "Lazio",
    "liguria": "Liguria",
    "lombardia": "Lombardia",
    "marche": "Marche",
    "molise": "Molise",
    "piemonte": "Piemonte",
    "puglia": "Puglia",
    "sardegna": "Sardegna",
    "sicilia": "Sicilia",
    "toscana": "Toscana",
    "trentino-alto-adige": "Trentino-Alto Adige",
    "umbria": "Umbria",
    "valle-d-aosta": "Valle d'Aosta",
    "veneto": "Veneto",
}

# Nomi alternativi delle regioni, già normalizzati (minuscolo, senza accenti).
_REGION_ALIASES: dict[str, list[str]] = {
    "abruzzo": ["abruzzo"],
    "basilicata": ["basilicata", "lucania"],
    "calabria": ["calabria"],
    "campania": ["campania"],
    "emilia-romagna": ["emilia-romagna", "emilia romagna"],
    "friuli-venezia-giulia": ["friuli-venezia giulia", "friuli venezia giulia", "friuli"],
    "lazio": ["lazio"],
    "liguria": ["liguria"],
    "lombardia": ["lombardia"],
    "marche": ["marche"],
    "molise": ["molise"],
    "piemonte": ["piemonte"],
    "puglia": ["puglia"],
    "sardegna": ["sardegna"],
    "sicilia": ["sicilia"],
    "toscana": ["toscana"],
    "trentino-alto-adige": ["trentino-alto adige", "trentino alto adige", "trentino"],
    "umbria": ["umbria"],
    "valle-d-aosta": ["valle d'aosta", "valle d aosta"],
    "veneto": ["veneto"],
}


@dataclass(frozen=True)
class Province:
    code: str  # sigla, es. "TO"
    name: str  # nome mostrato
    region: str  # codice regione
    aliases: tuple[str, ...]  # nomi normalizzati da cercare nel testo


def _p(code: str, name: str, region: str, *extra: str) -> Province:
    aliases = {norm(name), *(norm(e) for e in extra)}
    return Province(code, name, region, tuple(sorted(aliases, key=len, reverse=True)))


def norm(text: str) -> str:
    """Minuscolo, senza accenti, apostrofi e virgolette uniformati, spazi compattati."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"[’‘`´]", "'", text)
    text = re.sub(r"[“”«»]", '"', text)
    return re.sub(r"\s+", " ", text).strip()


PROVINCES: list[Province] = [
    # Piemonte
    _p("TO", "Torino", "piemonte"),
    _p("VC", "Vercelli", "piemonte"),
    _p("NO", "Novara", "piemonte"),
    _p("CN", "Cuneo", "piemonte"),
    _p("AT", "Asti", "piemonte"),
    _p("AL", "Alessandria", "piemonte"),
    _p("BI", "Biella", "piemonte"),
    _p("VB", "Verbano-Cusio-Ossola", "piemonte", "verbano cusio ossola", "verbania"),
    # Valle d'Aosta
    _p("AO", "Aosta", "valle-d-aosta"),
    # Lombardia
    _p("VA", "Varese", "lombardia"),
    _p("CO", "Como", "lombardia"),
    _p("SO", "Sondrio", "lombardia"),
    _p("MI", "Milano", "lombardia"),
    _p("BG", "Bergamo", "lombardia"),
    _p("BS", "Brescia", "lombardia"),
    _p("PV", "Pavia", "lombardia"),
    _p("CR", "Cremona", "lombardia"),
    _p("MN", "Mantova", "lombardia"),
    _p("LC", "Lecco", "lombardia"),
    _p("LO", "Lodi", "lombardia"),
    _p("MB", "Monza e della Brianza", "lombardia", "monza e brianza", "monza"),
    # Trentino-Alto Adige
    _p("BZ", "Bolzano", "trentino-alto-adige", "bolzano/bozen", "bozen"),
    _p("TN", "Trento", "trentino-alto-adige"),
    # Veneto
    _p("VR", "Verona", "veneto"),
    _p("VI", "Vicenza", "veneto"),
    _p("BL", "Belluno", "veneto"),
    _p("TV", "Treviso", "veneto"),
    _p("VE", "Venezia", "veneto"),
    _p("PD", "Padova", "veneto"),
    _p("RO", "Rovigo", "veneto"),
    # Friuli-Venezia Giulia
    _p("UD", "Udine", "friuli-venezia-giulia"),
    _p("GO", "Gorizia", "friuli-venezia-giulia"),
    _p("TS", "Trieste", "friuli-venezia-giulia"),
    _p("PN", "Pordenone", "friuli-venezia-giulia"),
    # Liguria
    _p("IM", "Imperia", "liguria"),
    _p("SV", "Savona", "liguria"),
    _p("GE", "Genova", "liguria"),
    _p("SP", "La Spezia", "liguria", "spezia"),
    # Emilia-Romagna
    _p("PC", "Piacenza", "emilia-romagna"),
    _p("PR", "Parma", "emilia-romagna"),
    _p("RE", "Reggio Emilia", "emilia-romagna", "reggio nell'emilia", "reggio nell emilia"),
    _p("MO", "Modena", "emilia-romagna"),
    _p("BO", "Bologna", "emilia-romagna"),
    _p("FE", "Ferrara", "emilia-romagna"),
    _p("RA", "Ravenna", "emilia-romagna"),
    _p("FC", "Forlì-Cesena", "emilia-romagna", "forli cesena", "forli"),
    _p("RN", "Rimini", "emilia-romagna"),
    # Toscana
    _p("MS", "Massa-Carrara", "toscana", "massa carrara", "massa"),
    _p("LU", "Lucca", "toscana"),
    _p("PT", "Pistoia", "toscana"),
    _p("FI", "Firenze", "toscana"),
    _p("LI", "Livorno", "toscana"),
    _p("PI", "Pisa", "toscana"),
    _p("AR", "Arezzo", "toscana"),
    _p("SI", "Siena", "toscana"),
    _p("GR", "Grosseto", "toscana"),
    _p("PO", "Prato", "toscana"),
    # Umbria
    _p("PG", "Perugia", "umbria"),
    _p("TR", "Terni", "umbria"),
    # Marche
    _p("PU", "Pesaro e Urbino", "marche", "pesaro-urbino", "pesaro"),
    _p("AN", "Ancona", "marche"),
    _p("MC", "Macerata", "marche"),
    _p("AP", "Ascoli Piceno", "marche", "ascoli"),
    _p("FM", "Fermo", "marche"),
    # Lazio
    _p("VT", "Viterbo", "lazio"),
    _p("RI", "Rieti", "lazio"),
    _p("RM", "Roma", "lazio"),
    _p("LT", "Latina", "lazio"),
    _p("FR", "Frosinone", "lazio"),
    # Abruzzo
    _p("AQ", "L'Aquila", "abruzzo", "aquila"),
    _p("TE", "Teramo", "abruzzo"),
    _p("PE", "Pescara", "abruzzo"),
    _p("CH", "Chieti", "abruzzo"),
    # Molise
    _p("CB", "Campobasso", "molise"),
    _p("IS", "Isernia", "molise"),
    # Campania
    _p("CE", "Caserta", "campania"),
    _p("BN", "Benevento", "campania"),
    _p("NA", "Napoli", "campania"),
    _p("AV", "Avellino", "campania"),
    _p("SA", "Salerno", "campania"),
    # Puglia
    _p("FG", "Foggia", "puglia"),
    _p("BA", "Bari", "puglia"),
    _p("TA", "Taranto", "puglia"),
    _p("BR", "Brindisi", "puglia"),
    _p("LE", "Lecce", "puglia"),
    _p("BT", "Barletta-Andria-Trani", "puglia", "barletta andria trani"),
    # Basilicata
    _p("PZ", "Potenza", "basilicata"),
    _p("MT", "Matera", "basilicata"),
    # Calabria
    _p("CS", "Cosenza", "calabria"),
    _p("CZ", "Catanzaro", "calabria"),
    _p("RC", "Reggio Calabria", "calabria", "reggio di calabria"),
    _p("KR", "Crotone", "calabria"),
    _p("VV", "Vibo Valentia", "calabria", "vibo"),
    # Sicilia
    _p("TP", "Trapani", "sicilia"),
    _p("PA", "Palermo", "sicilia"),
    _p("ME", "Messina", "sicilia"),
    _p("AG", "Agrigento", "sicilia"),
    _p("CL", "Caltanissetta", "sicilia"),
    _p("EN", "Enna", "sicilia"),
    _p("CT", "Catania", "sicilia"),
    _p("RG", "Ragusa", "sicilia"),
    _p("SR", "Siracusa", "sicilia"),
    # Sardegna (assetto 2026)
    _p("SS", "Sassari", "sardegna"),
    _p("NU", "Nuoro", "sardegna"),
    _p("CA", "Cagliari", "sardegna"),
    _p("OR", "Oristano", "sardegna"),
    _p("OT", "Gallura Nord-Est Sardegna", "sardegna",
       "gallura nord est sardegna", "gallura", "olbia-tempio", "olbia tempio"),
    _p("OG", "Ogliastra", "sardegna"),
    _p("VS", "Medio Campidano", "sardegna"),
    _p("SU", "Sulcis Iglesiente", "sardegna", "carbonia-iglesias", "carbonia iglesias"),
]

PROVINCE_BY_CODE: dict[str, Province] = {p.code: p for p in PROVINCES}

# Nomi superati che corrispondono a più province attuali.
_LEGACY_MULTI: dict[str, tuple[str, ...]] = {"sud sardegna": ("SU", "VS")}

assert len(PROVINCES) == 110, "Le province/città metropolitane devono essere 110"
assert all(p.region in REGIONS for p in PROVINCES)


def provinces_of_region(region: str) -> list[Province]:
    return [p for p in PROVINCES if p.region == region]


def region_of(province_code: str) -> str | None:
    p = PROVINCE_BY_CODE.get(province_code)
    return p.region if p else None


# --- Riconoscimento nel testo ------------------------------------------------

# Parole che, seguite da "di <nome>", indicano con buona certezza una provincia.
# Evitiamo di cercare i nomi "nudi" (es. "Prato", "Massa") perché sono anche
# nomi di località e darebbero falsi positivi.
_PREFIXES = (
    r"prefettura|prefetto|questura|questore|provincia|amministrazione provinciale"
    r"|citta metropolitana|libero consorzio comunale|ufficio territoriale del governo"
    r"|comando provinciale(?: dei carabinieri| dei vigili del fuoco| vigili del fuoco)?"
    r"|vigili del fuoco|polizia stradale|sezione polizia stradale|polstrada|carabinieri"
)
_PREPS = r"(?:di|del|della|dell'|dei)"


def _build_province_regex() -> re.Pattern[str]:
    names: list[tuple[str, tuple[str, ...]]] = []
    for p in PROVINCES:
        for a in p.aliases:
            names.append((a, (p.code,)))
    for legacy, codes in _LEGACY_MULTI.items():
        names.append((legacy, codes))
    names.sort(key=lambda x: len(x[0]), reverse=True)
    alternation = "|".join(re.escape(n) for n, _ in names)
    return re.compile(
        rf"\b(?:{_PREFIXES})\s+{_PREPS}\s*(?:l')?\s*({alternation})\b"
    )


_PROVINCE_RE = _build_province_regex()
_ALIAS_TO_CODES: dict[str, tuple[str, ...]] = {}
for _p_ in PROVINCES:
    for _a in _p_.aliases:
        _ALIAS_TO_CODES[_a] = (_p_.code,)
_ALIAS_TO_CODES.update(_LEGACY_MULTI)


def find_provinces(text: str) -> list[str]:
    """Sigle delle province citate nel testo (già normalizzato o no), in ordine di sigla."""
    t = norm(text)
    found: set[str] = set()
    for m in _PROVINCE_RE.finditer(t):
        found.update(_ALIAS_TO_CODES.get(m.group(1), ()))
    return sorted(found)


def find_regions(text: str) -> list[str]:
    """Codici delle regioni il cui nome compare nel testo."""
    t = norm(text)
    found = set()
    for code, aliases in _REGION_ALIASES.items():
        if any(re.search(rf"\b{re.escape(a)}\b", t) for a in aliases):
            found.add(code)
    # "Friuli" e "Trentino" sono sottostringhe dei nomi completi: già coperti.
    return sorted(found)
