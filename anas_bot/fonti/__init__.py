"""Fonti oltre ANAS: avvisi stradali pubblicati da altri gestori, trasformati in Ordinanza.

Ogni fonte produce oggetti Ordinanza con `source` impostato e un ord_id in una fascia propria (così non si
sovrappone mai agli ID di ANAS, che oggi sono intorno a 215.000):

- "bz":  Centrale Viabilità della Provincia di Bolzano (solo chiusure, JSON del bollettino) -> 1.000.000.000 + id
- "a22": Autostrada del Brennero (elenco avvisi del sito, in JSON)                         -> 2.000.000.000 + id

Da lì in poi il percorso è quello delle ordinanze ANAS: abbinamento alle zone, messaggi, riepilogo per i
nuovi iscritti, consegne. Le regole Waze sono le stesse: "chiusura" solo se un tratto (o una carreggiata,
una rampa) non si può percorrere.
"""

from __future__ import annotations

SOURCE_LABELS = {
    "": "ANAS",
    "bz": "Centrale Viabilità Provincia di Bolzano",
    "a22": "Autostrada del Brennero A22",
}
SOURCE_LINK_TEXT = {"": "📄 Apri PDF", "bz": "🔗 Apri il bollettino", "a22": "🔗 Apri gli avvisi A22"}
ID_OFFSET = {"bz": 1_000_000_000, "a22": 2_000_000_000}

# Waze Map Editor centrato sul punto dell'avviso (l'Italia è nell'ambiente "row"; zoom 18 = segmenti visibili)
WME_URL = "https://www.waze.com/it/editor?env=row&lat={lat:.6f}&lon={lon:.6f}&zoomLevel=18"


def wme_url(o) -> str:
    """Link a WME sul punto dell'avviso, se la fonte dà le coordinate (Bolzano: x = longitudine, y = latitudine)."""
    rec = o.listing_record or {}
    try:
        lon, lat = float(rec["x"]), float(rec["y"])
    except (KeyError, TypeError, ValueError):
        return ""
    if not (35 < lat < 48 and 6 < lon < 19):  # fuori dall'Italia: coordinate sbagliate, meglio nessun link
        return ""
    return WME_URL.format(lat=lat, lon=lon)
