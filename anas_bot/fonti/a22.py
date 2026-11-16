"""Autostrada del Brennero A22: gli avvisi della pagina "Viabilità > Avvisi", letti dal JSON che la pagina usa.

Endpoint: https://www.autobrennero.it/api/MapApi/GetAvvisi?culture=it (lo stesso che carica la mappa del
sito; non è un'API documentata, quindi se cambia formato il bot avvisa e salta la fonte). Ogni avviso ha:
id, titolo (testo con date e km), codiceIcona, kM_Inizio, kM_Fine, direzione ("nord", "sud", "entrambe").

Esempi reali (14/11/2026):
- 51 "Dalle ore 01:03 del 04/11/2026 alle ore 17:00 del 23/11/2026 scambio di carreggiata dal km 38.674 al
  km 37.553 tra Bressanone Zona Industriale e Vipiteno carreggiata nord"
- 54 "... deviazione di carreggiata con 2 flussi di marcia dal km 1.941 al km 6 tra Brennero Paese e Vipiteno
  carreggiata sud"
- 11 "... area di servizio Paganella ovest non eroga GPL" / 21 "Colonnine SOS fuori servizio ..." (non per Waze)

Regole Waze: lo scambio di carreggiata svuota una carreggiata (il traffico passa a doppio senso sull'altra):
è una chiusura di quella carreggiata. La "deviazione di carreggiata con 2 flussi di marcia" quasi sempre
anche, ma la dicitura è meno netta: parte come chiusura "da verificare". Se invece resta traffico "non
deviato" ("deviazione di carreggiata con 2 corsie per il traffico non deviato", 16/11/2026) la carreggiata
resta percorribile: non è una chiusura, va tra le altre ordinanze. Svincoli, uscite, entrate o caselli
"chiusi" sono chiusure di accessi.
"""

from __future__ import annotations

import re
from datetime import date

from ..anas.parser import CLOSURE, OTHER, Ordinanza
from . import ID_OFFSET

API_URL = "https://www.autobrennero.it/api/MapApi/GetAvvisi?culture=it"
PAGE_URL = "https://www.autobrennero.it/it/viabilita/avvisi/"

# Avvisi di servizio che non toccano la mappa: carburanti, colonnine SOS, ricarica
SKIP_ICONS = {11, 21}
_SKIP_TEXT = re.compile(r"\bGPL\b|metano|idrogeno|colonnin|non eroga|ricarica|carburant", re.I)
_AREA_CLOSED = re.compile(r"area di servizio chius[ao]\b", re.I)  # "area di servizio chiusa", icona 11 (16/11/2026)
_SWAP = re.compile(r"scambio di carreggiata", re.I)
_DEVIATION = re.compile(r"deviazione di carreggiata", re.I)
_NOT_DEVIATED = re.compile(r"\bnon deviat[oaie]\b", re.I)  # parte del traffico resta sulla sua carreggiata
_ACCESS_CLOSED = re.compile(r"\b(svincolo|uscita|entrata|casello|stazione|area di servizio|rampa)\b[^.\n]{0,60}?\bchius[aoe]\b"
                            r"|\bchiusur[ae]\b[^.\n]{0,40}?\b(svincolo|uscita|entrata|casello|stazione|area di servizio|rampa)\b",
                            re.I)
_ROAD_CLOSED = re.compile(r"\bchiusura (?:totale|(?:della |di )?carreggiata|al traffico)\b|\bcarreggiata chiusa\b"
                          r"|\bautostrada chiusa\b|\bchiusura (?:del)?l'autostrada\b", re.I)
# chiusa solo una corsia ("chiusura corsia di sorpasso", "chiusura al traffico della corsia di emergenza",
# "chiusura della corsia di accelerazione dello svincolo"): restringimento, per Waze non è una chiusura
_LANE_ONLY = re.compile(r"\bchius\w*\s+(?:al traffico\s+)?(?:della\s+|delle\s+|di\s+|dell')?(?:\w+\s+)?corsi[ae]\b", re.I)
_WHEN = re.compile(r"(?:dalle|alle) ore (\d{1,2}:\d{2}) del (\d{2})/(\d{2})/(\d{4})", re.I)

# km della A22 -> provincia (confini approssimati ai caselli: Salorno ~km 125, Borghetto ~km 197,
# Nogarole Rocca/Mantova ~km 252, Reggiolo ~km 295, Carpi ~km 302)
_KM_PROVINCES = ((125, "BZ"), (197, "TN"), (252, "VR"), (295, "MN"), (302, "RE"), (10_000, "MO"))
_REGION = {"BZ": "trentino-alto-adige", "TN": "trentino-alto-adige", "VR": "veneto", "MN": "lombardia",
           "RE": "emilia-romagna", "MO": "emilia-romagna"}


def provinces_for_km(km_a: float, km_b: float) -> list[str]:
    lo, hi = sorted((km_a, km_b))
    out: list[str] = []
    prev = 0.0
    for limit, prov in _KM_PROVINCES:
        if lo < limit and hi >= prev:
            out.append(prov)
        prev = limit
    return out


def _km(v) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return ""
    return f"{int(x)}+{round((x - int(x)) * 1000):03d}"


def skip_reason(item: dict) -> str:
    """Perché un avviso A22 non riguarda la mappa ("" = si tiene, come chiusura o tra le altre ordinanze)."""
    if not str(item.get("id", "")).strip().isdigit():
        return "numero dell'avviso mancante"
    text = " ".join(str(item.get("titolo", "")).split())
    if not text:
        return "testo vuoto"
    if _AREA_CLOSED.search(text):  # area chiusa del tutto (non solo il carburante): per Waze conta
        return ""
    try:
        icon = int(item.get("codiceIcona") or 0)
    except (TypeError, ValueError):
        icon = 0
    if icon in SKIP_ICONS or _SKIP_TEXT.search(text):
        return "servizio (carburanti, colonnine SOS, ricarica)"
    return ""


def item_to_ordinanza(item: dict) -> Ordinanza | None:
    if skip_reason(item):
        return None
    aid = int(str(item["id"]).strip())
    text = " ".join(str(item.get("titolo", "")).split())
    try:
        icon = int(item.get("codiceIcona") or 0)
    except (TypeError, ValueError):
        icon = 0

    category, ramp_only, access, uncertain, why = OTHER, False, "", False, ""
    if _LANE_ONLY.search(text):
        pass  # resta "altro"
    elif _SWAP.search(text):
        category, ramp_only, access = CLOSURE, True, "carreggiata"
    elif _DEVIATION.search(text) and not _NOT_DEVIATED.search(text):
        category, ramp_only, access = CLOSURE, True, "carreggiata"
        uncertain, why = True, "deviazione di carreggiata: di solito la carreggiata indicata è chiusa e il traffico passa sull'altra"
    elif (m := _ACCESS_CLOSED.search(text)):
        kind = (m.group(1) or m.group(2) or "").lower()
        category, ramp_only, access = CLOSURE, True, {"uscita": "svincolo", "entrata": "svincolo", "casello": "svincolo",
                                                      "stazione": "svincolo"}.get(kind, kind)
    elif (m := _ROAD_CLOSED.search(text)):
        category = CLOSURE
        if "carreggiata" in m.group(0).lower():  # una sola carreggiata: "CARREGGIATA CHIUSA"
            ramp_only, access = True, "carreggiata"

    times = _WHEN.findall(text)
    start = end = ""
    if times:
        hh, d, m_, y = times[0]
        start = date(int(y), int(m_), int(d)).isoformat()
        if len(times) > 1:
            hh2, d2, m2, y2 = times[-1]
            end = date(int(y2), int(m2), int(d2)).isoformat()

    try:
        km_a, km_b = float(item.get("kM_Inizio")), float(item.get("kM_Fine"))
    except (TypeError, ValueError):
        km_a = km_b = None
    provinces = provinces_for_km(km_a, km_b) if km_a is not None else []
    direction = str(item.get("direzione", "")).strip().lower()
    direction = {"nord": "carreggiata nord (verso il Brennero)", "sud": "carreggiata sud (verso Modena)",
                 "entrambe": "entrambe le direzioni"}.get(direction, direction)
    km_from, km_to = (_km(item.get("kM_Inizio")), _km(item.get("kM_Fine")))
    return Ordinanza(
        ord_id=ID_OFFSET["a22"] + aid,
        category=category,
        pdf_url=PAGE_URL,
        number="",
        structure="Autostrada del Brennero",
        roads=["A22"],
        road_names={"A22": "del Brennero"},
        km_from=km_from,
        km_to=km_to if km_to != km_from else "",
        provinces=provinces,
        regions=sorted({_REGION[p] for p in provinces}),
        province_inferred=True,
        start_date=start,
        end_date=end,
        open_ended=False,
        ramp_only=ramp_only,
        access_kind=access,
        direction=direction,
        excerpt=text,
        uncertain=uncertain,
        uncertain_why=why,
        source="a22",
        listing_record={"id": str(item.get("id")), "codiceIcona": icon},
    )


def parse_avvisi(data) -> list[Ordinanza]:
    if not isinstance(data, list):
        raise ValueError("A22: risposta inattesa (non è un elenco di avvisi)")
    out = []
    for item in data:
        if isinstance(item, dict):
            o = item_to_ordinanza(item)
            if o is not None:
                out.append(o)
    return out
