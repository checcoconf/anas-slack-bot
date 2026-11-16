"""Centrale Viabilità della Provincia di Bolzano: solo le CHIUSURE stradali, dal JSON del bollettino.

Fonte: https://static-verkehr.provinz.bz.it/publications/traffic/traffic.json, lo stesso file che carica la
pagina https://traffico.provincia.bz.it (vista "Testo"). Rispetto al feed RSS ha le date di inizio e di FINE
("fino al 11/12/2026" del sito) e il grado di ogni avviso. Ogni voce ha, tra l'altro:
- messageId: numero dell'avviso + 2 cifre di categoria (3071701 = "Situazione attuale", 3071712 = "Cantieri"):
  la stessa notizia compare in più categorie, il numero di base (messageId // 100) è uno solo;
- messageGradId: 3 = "traffico bloccato" (chiusura), 4 = "rallentamenti", 5 = "percorribile liberamente";
- messageTypeId: 1 situazione attuale, 8 passi, 10 trasporti pubblici, 11 fuori provincia, 12 cantieri e
  chiusure, 13 percorsi ciclabili; messageZoneId 8 = "Fuori Alto Adige";
- messageStreetNr + messageStreetInternetDescIt: la strada ("SS38" "Passo dello Stelvio", "LS/SP104" "Laudes",
  "" "Comune di Merano"); placeIt: il testo in italiano; beginDate, endDate (vuota = non detta).

Chiusura = testo in MAIUSCOLO (CHIUSA, CHIUSI, CHIUSURA NOTTURNA, CHIUSURA INVERNALE), con grado 3 o 4. Tutto il resto
(cantieri, sensi unici alternati, "chiusure temporanee fino a 10 minuti", divieti per categorie) si scarta: la
Provincia è partner di Waze e quegli avvisi li inserisce già lei, mentre le chiusure dei segmenti le fanno gli
editor (indicazione dello SM di zona, 14/11/2026). X/Y (coordinate WGS84) servono per il link a WME.
"""

from __future__ import annotations

import re
from datetime import date

from ..anas.parser import CLOSURE, Ordinanza
from . import ID_OFFSET

FEED_URL = "https://static-verkehr.provinz.bz.it/publications/traffic/traffic.json"
PAGE_URL = "https://traffico.provincia.bz.it/it/home#tab_text"  # si apre già sulla vista "Testo" (elenco avvisi)


def is_updated_now(when) -> bool:
    """Il bollettino è aggiornato lun-sab 06:30-20:00, domeniche e festivi 08:00-20:00 (pagina del bollettino,
    14/11/2026). Fuori da queste fasce non cambia: niente richieste. Margine: dalle 6 (dalle 8 la domenica)
    fino alle 20:59, così si prende anche l'ultimo aggiornamento delle 20. I festivi infrasettimanali si
    leggono come i feriali (una richiesta in più, nessun danno)."""
    start = 8 if when.weekday() == 6 else 6
    return start <= when.hour <= 20


FREE = "5"                           # messageGradId: percorribile liberamente (3 = bloccato, 4 = rallentamenti)
SKIP_TYPES = {"10", "11", "13"}      # trasporti pubblici, fuori provincia, percorsi ciclabili
SKIP_ZONES = {"8"}                   # fuori Alto Adige (es. SS42 Passo Mendola - Ronzone, in Trentino)
SKIP_STREETS = ("ferrovia",)

# chiusure vere: MAIUSCOLO nel testo (case-sensitive di proposito)
_CLOSED = re.compile(r"\bCHIUS[AOEI]\b|\bCHIUSUR[AE]\b|\bINTERROTT[AOEI]\b")  # "strada INTERROTTA" (frana) = chiusa
# chiusura solo per alcune categorie di veicoli -> non è una chiusura per Waze
_ONLY_SOME = re.compile(r"CHIUS\w*\s+(?:al traffico\s+)?(?:per|ai)\s+(?:autobus|autoarticolat|autotren|veicoli|mezzi pesanti|camion|biciclett|cicli)",
                        re.I)
_ROAD = re.compile(r"^\s*(?:LS/)?(SS|SP|SC|SR|A)\s*(\d+)\s*(bis|ter|dir|var)?\b\s*(.*)$", re.I)
_KM = re.compile(r"km\s*(\d+)\s*[,.]\s*(\d{1,3})")
_HOURS = re.compile(r"dalle ore\s*(\d{1,2})[:.](\d{2})\s*alle ore\s*(\d{1,2})[:.](\d{2})", re.I)
_WINTER = re.compile(r"CHIUSURA INVERNALE")
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# "Da mercoledì 18.11.2026: ...", "CHIUSURA al traffico da sabato 21.11.2026 - ore 00:00 a ...": l'inizio vero
_FROM = re.compile(r"\bda\s+(?:lun|mar|mer|gio|ven|sab|dom)\w*\s+(\d{1,2})\.(\d{1,2})\.(20\d\d)", re.I)


def _km(m: re.Match) -> str:
    return f"{int(m.group(1))}+{m.group(2).ljust(3, '0')}"


def _road(nr: str, name: str) -> tuple[list[str], dict[str, str]]:
    """("SS38", "Passo dello Stelvio") -> (["SS38"], {"SS38": "Passo dello Stelvio"}); ("LS/SP 44", ...) ->
    "SP44"; ("SS44Bis", ...) -> "SS44bis"; ("", "Comune di Merano") -> (["Comune di Merano"], {})."""
    name = " ".join(name.split())
    m = _ROAD.match(" ".join(nr.split()))
    if m:
        code = m.group(1).upper() + m.group(2) + (m.group(3) or "").lower()
        return [code], ({code: name} if name else {})
    return ([name] if name else []), {}


def _day(v) -> str:
    v = str(v or "").strip()[:10]
    return v if _ISO.match(v) else ""


def _start(begin: str, end: str, text: str) -> str:
    """Il bollettino pubblica l'avviso dal giorno prima: beginDate 17/11 per "Da mercoledì 18.11.2026: ...
    CHIUSURA" (16/11/2026). Se il testo dice da quando, vale il testo (purché dentro beginDate-endDate)."""
    m = _FROM.search(text)
    if not m:
        return begin
    try:
        said = date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
    except ValueError:
        return begin
    return said if (not begin or said >= begin) and (not end or said <= end) else begin


def _s(item: dict, key: str) -> str:
    return " ".join(str(item.get(key) or "").split())


def skip_reason(item: dict) -> str:
    """Perché una voce del bollettino NON è una chiusura da mandare ("" = è da mandare)."""
    street, text = _s(item, "messageStreetInternetDescIt"), _s(item, "placeIt")
    if _s(item, "messageTypeId") in SKIP_TYPES:
        return f"categoria \"{_s(item, 'messageTypeDescIt') or _s(item, 'messageTypeId')}\""
    if _s(item, "messageZoneId") in SKIP_ZONES:
        return "fuori Alto Adige"
    if street.lower().startswith(SKIP_STREETS):
        return "ferrovia"
    if street.endswith(":"):
        return "riepilogo generale (\"… e passi:\"): i singoli passi hanno un avviso proprio"
    if _s(item, "messageGradId") == FREE:
        return "percorribile liberamente"
    # il grado non basta: "A Brunico CHIUSURA dopo un incidente" ha grado 4 (16/11/2026). Decide il MAIUSCOLO.
    if not _CLOSED.search(text):
        return "non è una chiusura (niente CHIUSA/CHIUSURA/INTERROTTA in maiuscolo): la Provincia lo inserisce già in Waze"
    if _ONLY_SOME.search(text):
        return "chiusa solo per alcuni veicoli"
    if not _s(item, "messageId").isdigit():
        return "numero dell'avviso mancante"
    return ""


def item_to_ordinanza(item: dict) -> Ordinanza | None:
    """Una voce del bollettino -> Ordinanza se è una chiusura stradale in Alto Adige, altrimenti None."""
    if skip_reason(item):
        return None
    s = lambda k: _s(item, k)  # noqa: E731
    street, text = s("messageStreetInternetDescIt"), s("placeIt")
    base_id = int(s("messageId")) // 100

    roads, names = _road(s("messageStreetNr"), street)
    kms = list(_KM.finditer(text))
    end = _day(item.get("endDate"))
    start = _start(_day(item.get("beginDate")), end, text)
    winter = bool(_WINTER.search(text))
    hours = _HOURS.search(text)
    return Ordinanza(
        ord_id=ID_OFFSET["bz"] + base_id,
        category=CLOSURE,
        pdf_url=PAGE_URL,
        number="",
        structure="Provincia di Bolzano",
        roads=roads,
        road_names=names,
        km_from=_km(kms[0]) if kms else "",
        km_to=_km(kms[1]) if len(kms) > 1 else "",
        provinces=["BZ"],
        regions=["trentino-alto-adige"],
        province_inferred=True,
        start_date=start,
        end_date=end,
        open_ended=winter and not end,  # "fino a nuova disposizione" solo per le chiusure invernali dei passi
        time_window=(f"{int(hours.group(1)):02d}:{hours.group(2)}-{int(hours.group(3)):02d}:{hours.group(4)}"
                     if hours else ""),
        excerpt=("Chiusura invernale. " + text) if winter else text,
        source="bz",
        listing_record={"messageId": s("messageId"), "type": s("messageTypeDescIt"),
                        "x": item.get("X"), "y": item.get("Y")},
    )


def parse_traffic(data) -> list[Ordinanza]:
    """Le chiusure del bollettino, una per notizia (i doppioni tra categorie si uniscono)."""
    if not isinstance(data, list):
        raise ValueError("Bolzano: risposta inattesa (non è un elenco di avvisi)")
    out: dict[int, Ordinanza] = {}
    for item in data:
        if isinstance(item, dict) and (o := item_to_ordinanza(item)) is not None:
            out.setdefault(o.ord_id, o)
    return list(out.values())
