"""Centrale Viabilità della Provincia di Bolzano: feed RSS ufficiale, in italiano.

Feed: https://static-traffico.provincia.bz.it/publications/rss/tutte-le-categorie.xml (indirizzo valido dal
novembre 2026; il vecchio endpoint SIAG resta attivo fino al 30/11/2026). Ogni voce ha:
- <guid>: numero dell'avviso + 2 cifre di categoria (3071701 = "Situazione attuale", 3071712 = "Cantieri"):
  la stessa notizia compare in più categorie, il numero di base (guid // 100) è uno solo;
- <title>: la strada ("SS12 dell'Abetone e del Brennero", "LS/SP3 Val Senales", "Comune di Merano");
- <description>: testo libero con km, orari e date; le chiusure vere sono in MAIUSCOLO ("è CHIUSA al
  traffico", "CHIUSURA NOTTURNA", "CHIUSURA INVERNALE"), le "chiusure temporanee fino a 15 minuti" in
  minuscolo e per Waze non sono chiusure;
- <pubDate>: in pratica la data di INIZIO dell'avviso (ci sono date future), non di pubblicazione;
- <category>: "Cantieri stradali / Chiusure", "Passi e vie di montagna", "Situazione attuale", "Percorsi
  ciclabili", "Trasporti pubblici", "Fuori provincia".
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from datetime import date
from email.utils import parsedate_to_datetime

from ..anas.parser import CLOSURE, OTHER, Ordinanza
from . import ID_OFFSET

log = logging.getLogger(__name__)

FEED_URL = "https://static-traffico.provincia.bz.it/publications/rss/tutte-le-categorie.xml"


def is_updated_now(when) -> bool:
    """Il bollettino è aggiornato lun-sab 06:30-20:00, domeniche e festivi 08:00-20:00 (pagina del bollettino,
    14/11/2026). Fuori da queste fasce non cambia: niente richieste. Margine: dalle 6 (dalle 8 la domenica)
    fino alle 20:59, così si prende anche l'ultimo aggiornamento delle 20. I festivi infrasettimanali si
    leggono come i feriali (una richiesta in più, nessun danno)."""
    start = 8 if when.weekday() == 6 else 6
    return start <= when.hour <= 20
PAGE_URL = "https://traffico.provincia.bz.it/it/"

# categorie che non riguardano la mappa stradale (o non la provincia)
SKIP_CATEGORIES = ("percorsi ciclabili", "trasporti pubblici", "fuori provincia", "controlli radar")
SKIP_TITLES = ("ferrovia",)

# chiusure vere: MAIUSCOLO (case-sensitive di proposito)
_CLOSED = re.compile(r"\bCHIUS[AOE]\b|\bCHIUSURA\b")
# chiusura solo per alcune categorie di veicoli -> non è una chiusura per Waze
_ONLY_SOME = re.compile(r"CHIUS\w*\s+(?:al traffico\s+)?(?:per|ai)\s+(?:autobus|autoarticolat|autotren|veicoli|mezzi pesanti|camion|biciclett|cicli)",
                        re.I)
_NOTHING = re.compile(r"^\s*nessuna limitazione\.?\s*$", re.I)
_ROAD = re.compile(r"^\s*(?:LS/)?(SS|SP|SC|SR|A)\s*(\d+\s*(?:bis|ter|dir|var)?)\b\s*(.*)$", re.I)
_KM = re.compile(r"km\s*(\d+)\s*[,.]\s*(\d{1,3})")
_DATE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(20\d\d)\b")
_HOURS = re.compile(r"dalle ore\s*(\d{1,2})[:.](\d{2})\s*alle ore\s*(\d{1,2})[:.](\d{2})", re.I)
_WINTER = re.compile(r"CHIUSURA INVERNALE")


def _km(m: re.Match) -> str:
    return f"{int(m.group(1))}+{m.group(2).ljust(3, '0')}"


def _road(title: str) -> tuple[list[str], dict[str, str]]:
    """"SS12 dell'Abetone e del Brennero" -> (["SS12"], {"SS12": "dell'Abetone e del Brennero"});
    "LS/SP3 Val Senales" -> (["SP3"], ...); "Comune di Merano" -> (["Comune di Merano"], {})."""
    t = " ".join(title.split())
    m = _ROAD.match(t)
    if m:
        code = (m.group(1).upper() + m.group(2).replace(" ", "")).upper()
        name = m.group(3).strip()
        return [code], ({code: name} if name else {})
    return ([t] if t else []), {}


def _dates(text: str, start: date | None) -> tuple[str, str, bool]:
    """(inizio, fine, _) dal testo: "fino a lunedì 16.11.2026", "da sabato 21.11.2026 ... a domenica
    22.11.2026", "Da martedì 17.11.2026 - ore 00:00: ...". Fine vuota = non detta (l'avviso sparisce dal
    bollettino quando finisce: lo chiude il poller)."""
    found = []
    for d, m, y in _DATE.findall(text):
        try:
            found.append(date(int(y), int(m), int(d)))
        except ValueError:
            continue
    begin = start
    end = None
    if found:
        low = text.lower()
        if len(found) == 1 and not re.search(r"\bfino\b|\ba (?:lun|mar|mer|gio|ven|sab|dom)\w*\s+\d", low):
            begin = found[0]  # "Da martedì 17.11.2026": è l'inizio, la fine non è detta
        else:
            if len(found) > 1:
                begin = found[0]
            end = found[-1]
            if begin and end < begin:
                end = None
    return (begin.isoformat() if begin else ""), (end.isoformat() if end else ""), False


def item_to_ordinanza(guid: str, title: str, description: str, category: str, pub_date: str) -> Ordinanza | None:
    """Un avviso del feed -> Ordinanza, o None se non riguarda la mappa (ciclabili, treni, "nessuna limitazione")."""
    cat = category.strip().lower()
    title = " ".join(title.split())
    text = " ".join(description.split())
    if any(c in cat for c in SKIP_CATEGORIES) or title.lower().startswith(SKIP_TITLES):
        return None
    if not text or _NOTHING.match(text) or title.endswith(":"):  # riepiloghi generici ("Strade di montagna alte e passi:")
        return None
    try:
        base_id = int(guid.strip()) // 100
    except ValueError:
        return None
    try:
        start = parsedate_to_datetime(pub_date).date() if pub_date else None
    except (TypeError, ValueError):
        start = None

    closed = bool(_CLOSED.search(text)) and not _ONLY_SOME.search(text)
    roads, names = _road(title)
    kms = list(_KM.finditer(text))
    begin, end, _ = _dates(text, start)
    open_ended = bool(_WINTER.search(text)) and not end  # "fino a nuova disposizione" solo per i passi chiusi d'inverno
    hours = _HOURS.search(text)
    o = Ordinanza(
        ord_id=ID_OFFSET["bz"] + base_id,
        category=CLOSURE if closed else OTHER,
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
        start_date=begin,
        end_date=end,
        open_ended=open_ended,
        time_window=(f"{int(hours.group(1)):02d}:{hours.group(2)}-{int(hours.group(3)):02d}:{hours.group(4)}"
                     if hours and closed else ""),
        excerpt=text,
        source="bz",
        listing_record={"guid": guid.strip(), "title": title, "category": category.strip(), "pubDate": pub_date},
    )
    if _WINTER.search(text):
        o.excerpt = "Chiusura invernale. " + text
    return o


def parse_feed(xml_text: str) -> list[Ordinanza]:
    """Tutti gli avvisi utili del feed, un'Ordinanza per notizia (i doppioni tra categorie si uniscono)."""
    root = ET.fromstring(xml_text)
    out: dict[int, Ordinanza] = {}
    for item in root.iter("item"):
        def val(tag: str) -> str:
            el = item.find(tag)
            return el.text or "" if el is not None else ""
        o = item_to_ordinanza(val("guid"), val("title"), val("description"), val("category"), val("pubDate"))
        if o is None:
            continue
        prev = out.get(o.ord_id)
        # la stessa notizia in due categorie: vince la versione "chiusura" (di solito sono identiche)
        if prev is None or (o.category == CLOSURE and prev.category != CLOSURE):
            out[o.ord_id] = o
    return list(out.values())
