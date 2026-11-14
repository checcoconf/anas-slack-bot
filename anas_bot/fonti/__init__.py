"""Fonti oltre ANAS: avvisi stradali pubblicati da altri gestori, trasformati in Ordinanza.

Ogni fonte produce oggetti Ordinanza con `source` impostato e un ord_id in una fascia propria (così non si
sovrappone mai agli ID di ANAS, che oggi sono intorno a 215.000):

- "bz":  Centrale Viabilità della Provincia di Bolzano (feed RSS ufficiale in italiano) -> 1.000.000.000 + id
- "a22": Autostrada del Brennero (elenco avvisi del sito, in JSON)                    -> 2.000.000.000 + id

Da lì in poi il percorso è quello delle ordinanze ANAS: abbinamento alle zone, messaggi, riepilogo per i
nuovi iscritti, consegne. Le regole Waze sono le stesse: "chiusura" solo se un tratto (o una carreggiata,
una rampa) non si può percorrere; sensi unici alternati, restringimenti, limiti di cantiere vanno tra le
"altre ordinanze".
"""

from __future__ import annotations

SOURCE_LABELS = {
    "": "ANAS",
    "bz": "Centrale Viabilità Provincia di Bolzano",
    "a22": "Autostrada del Brennero A22",
}
SOURCE_LINK_TEXT = {"": "📄 Apri PDF", "bz": "🔗 Apri il bollettino", "a22": "🔗 Apri gli avvisi A22"}
ID_OFFSET = {"bz": 1_000_000_000, "a22": 2_000_000_000}


def source_of(ord_id: int) -> str:
    """La fonte di un ord_id dalla sua fascia ("" = ANAS)."""
    if ord_id >= ID_OFFSET["a22"]:
        return "a22"
    if ord_id >= ID_OFFSET["bz"]:
        return "bz"
    return ""
