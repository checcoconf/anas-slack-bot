"""Casi limite delle fonti oltre ANAS: nessuna chiusura persa, nessuna chiusura inventata.

Ogni riga è un avviso (testi reali o scritti come li scrivono la Provincia di Bolzano e l'A22) con il risultato
atteso. Se una fonte cambia modo di scrivere, si aggiunge qui la riga nuova.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from anas_bot.anas.parser import CLOSURE, OTHER
from anas_bot.db import Database
from anas_bot.fonti import ID_OFFSET, a22, bolzano, wme_url
from anas_bot.fonti.poller import FontiPoller
from anas_bot.views import ordinanza_blocks, title_line


def _bz(text: str, **over) -> dict:
    item = {"messageId": "3170012", "beginDate": "2026-11-16", "endDate": "2026-11-30", "messageGradId": "3",
            "messageTypeId": "12", "messageTypeDescIt": "Cantieri stradali / Chiusure", "messageZoneId": "4",
            "messageStreetNr": "SS12", "messageStreetInternetDescIt": "dell'Abetone e del Brennero", "placeIt": text,
            "X": 11.33, "Y": 46.43}
    item.update(over)
    return item


# --- Provincia di Bolzano: cosa è una chiusura -------------------------------------------------------------

BZ_CLOSED = [
    "A Laives (km 420,100 - km 420,300) CHIUSURA al traffico dalle ore 21:00 alle ore 05:00 per lavori.",
    "Nella galleria di Naturno (km 184,250 - km 187,100) CHIUSURA NOTTURNA dalle ore 19:00 alle ore 06:00.",
    "La via delle Palade è CHIUSA per tutti i mezzi fino a lunedì 16.11.2026.",
    "La strada comunale \"Unterblabach\" é CHIUSA al traffico dalle ore 07:00 alle ore 18:00 a causa di lavori.",
    "Per la partita di calcio viale Trieste e via Trento vengono CHIUSI al traffico dalle ore 12:00.",
    "Per la manifestazione le seguenti strade sono CHIUSE per il tempo necessario al transito della sfilata.",
    "Il tratto è CHIUSO al traffico per caduta massi.",
    "Dall'incrocio Tre Fontane in poi (km 124,300 – km 137,500) CHIUSURA INVERNALE.",
    "Tra S. Elena e S. Valburga CHIUSURE al traffico dalle ore 08:00 alle ore 12:00.",
    "La strada è INTERROTTA a causa di una frana.",
    "A Brunico (km 0,500 - km 1,000) CHIUSURA dopo un incidente",
]

BZ_NOT_CLOSED = [
    "A Vadena (km 8,350) senso unico alternato per sostituzione di coperchi di pozzetti.",
    "A San Pietro a tratti senso unico alternato e chiusure temporanee di 10 minuti dalle ore 07:30.",
    "All'entrata della val Senales senso unico alternato con chiusure temporanee fino a 10 minuti.",
    "Tra Eores ed il Passo delle Erbe divieto di transito per autobus e per veicoli di peso superiore a 24 t.",
    "La strada è CHIUSA per autobus e mezzi pesanti.",
    "CHIUSURA al traffico per veicoli superiori a 7,5 t.",
    "Strada chiusa per lavori (scritto in minuscolo: per la Provincia non è una chiusura).",
    "Nessuna limitazione.",
    "Rallentamenti per lavori di asfaltatura.",
    "",
]


@pytest.mark.parametrize("text", BZ_CLOSED)
def test_bz_every_way_of_writing_a_closure_is_kept(text):
    o = bolzano.item_to_ordinanza(_bz(text))
    assert o is not None and o.category == CLOSURE, bolzano.skip_reason(_bz(text))
    assert o.provinces == ["BZ"] and o.source == "bz" and o.pdf_url == bolzano.PAGE_URL


@pytest.mark.parametrize("text", BZ_NOT_CLOSED)
def test_bz_what_is_not_a_closure_is_dropped(text):
    assert bolzano.item_to_ordinanza(_bz(text)) is None and bolzano.skip_reason(_bz(text))


@pytest.mark.parametrize("over, why", [
    ({"messageTypeId": "10", "messageTypeDescIt": "Trasporti pubblici"}, "Trasporti pubblici"),
    ({"messageTypeId": "11", "messageTypeDescIt": "Fuori provincia"}, "Fuori provincia"),
    ({"messageTypeId": "13", "messageTypeDescIt": "Percorsi ciclabili"}, "Percorsi ciclabili"),
    ({"messageZoneId": "8"}, "fuori Alto Adige"),
    ({"messageStreetInternetDescIt": "Ferrovia", "messageStreetNr": ""}, "ferrovia"),
    ({"messageStreetInternetDescIt": "Strade di montagna alte e passi:", "messageStreetNr": ""}, "riepilogo"),
    ({"messageGradId": "5"}, "percorribile"),
    ({"messageId": ""}, "numero"),
])
def test_bz_closures_outside_the_map_are_dropped_with_a_reason(over, why):
    item = _bz("La strada è CHIUSA al traffico.", **over)
    assert bolzano.item_to_ordinanza(item) is None and why in bolzano.skip_reason(item)


@pytest.mark.parametrize("grade", ["3", "4", "", None])
def test_bz_grade_does_not_hide_a_closure(grade):
    assert bolzano.item_to_ordinanza(_bz("Tratto CHIUSO al traffico.", messageGradId=grade)) is not None


@pytest.mark.parametrize("nr, name, road", [
    ("SS38", "Passo dello Stelvio", ["SS38"]),
    ("LS/SP104", "Laudes", ["SP104"]),
    ("LS/SP 44", "Passo Stalle", ["SP44"]),
    ("SS44Bis", "Passo del Rombo", ["SS44bis"]),
    ("", "Comune di Merano", ["Comune di Merano"]),
    (" ", "Comune di Luson", ["Comune di Luson"]),
    (None, "Comune di Bolzano", ["Comune di Bolzano"]),
])
def test_bz_road_names(nr, name, road):
    o = bolzano.item_to_ordinanza(_bz("CHIUSURA al traffico.", messageStreetNr=nr, messageStreetInternetDescIt=name))
    assert o.roads == road


@pytest.mark.parametrize("begin, end, text, start", [
    ("2026-11-17", "2026-11-20", "Da mercoledì 18.11.2026: CHIUSURA al traffico.", "2026-11-18"),
    ("2026-11-20", "2026-11-22", "CHIUSURA al traffico da sabato 21.11.2026 - ore 00:00 a domenica 22.11.2026.", "2026-11-21"),
    ("2026-11-13", "2026-11-15", "CHIUSURA da venerdì 13.11.2026 fino domenica 15.11.2026.", "2026-11-13"),
    ("2026-11-16", "2026-11-20", "CHIUSURA al traffico dalle ore 08:00 alle ore 17:00.", "2026-11-16"),
    # data del testo fuori dal periodo della Provincia (refuso): vale il bollettino
    ("2026-11-17", "2026-11-20", "Da mercoledì 18.12.2026: CHIUSURA al traffico.", "2026-11-17"),
    ("2026-11-17", "2026-11-20", "Da mercoledì 31.02.2026: CHIUSURA al traffico.", "2026-11-17"),
    ("", "", "CHIUSURA al traffico.", ""),
])
def test_bz_start_date(begin, end, text, start):
    o = bolzano.item_to_ordinanza(_bz(text, beginDate=begin, endDate=end))
    assert o.start_date == start and o.end_date == end


def test_bz_same_closure_in_three_categories_is_one_message():
    items = [_bz("Tratto CHIUSO al traffico.", messageId=f"31700{c}", messageTypeId=t)
             for c, t in (("01", "1"), ("08", "8"), ("12", "12"))]
    got = bolzano.parse_traffic(items)
    assert [o.ord_id for o in got] == [ID_OFFSET["bz"] + 31700]


def test_bz_odd_items_never_break_the_list():
    items = [None, "testo", 42, {}, {"messageId": "x"}, _bz("Tratto CHIUSO.")]
    assert len(bolzano.parse_traffic(items)) == 1


# --- A22 ---------------------------------------------------------------------------------------------------

def _a22(text: str, icon: int = 51, km=(37.5, 38.6), direction: str = "nord", aid: str = "630001") -> dict:
    return {"id": aid, "codiceIcona": icon, "kM_Inizio": km[0], "kM_Fine": km[1], "direzione": direction,
            "titolo": "Dalle ore 20:00 del 16/11/2026 alle ore 06:00 del 17/11/2026\r\n" + text}


A22_CASES = [
    # (testo, icona, categoria attesa, accesso atteso)
    ("scambio di carreggiata\r\ndal km 38.674 al km 37.553 carreggiata nord", 51, CLOSURE, "carreggiata"),
    ("deviazione di carreggiata con 2 flussi di marcia\r\ndal km 1.941 al km 6", 54, CLOSURE, "carreggiata"),
    ("deviazione di carreggiata con 2 corsie per il traffico non deviato", 55, OTHER, ""),
    ("chiusura svincolo in entrata\r\ndella stazione autostradale di Trento Nord", 7, CLOSURE, "svincolo"),
    ("chiusura svincolo in uscita\r\ndella stazione autostradale di Bolzano Sud", 7, CLOSURE, "svincolo"),
    ("uscita chiusa\r\nalla stazione di Bressanone", 7, CLOSURE, "svincolo"),
    ("chiusura dell'entrata di Rovereto Sud", 7, CLOSURE, "svincolo"),
    ("casello di Affi chiuso", 7, CLOSURE, "svincolo"),
    ("area di servizio chiusa\r\nin area di servizio Adige ovest", 11, CLOSURE, "area di servizio"),
    ("chiusura carreggiata sud", 51, CLOSURE, "carreggiata"),
    ("chiusura della carreggiata nord", 51, CLOSURE, "carreggiata"),
    ("chiusura totale al traffico tra Brennero e Vipiteno", 51, CLOSURE, ""),
    ("autostrada chiusa tra Ala e Affi", 51, CLOSURE, ""),
    ("chiusura corsia di sorpasso", 53, OTHER, ""),
    ("chiusura al traffico della corsia di emergenza", 53, OTHER, ""),
    ("chiusura della corsia di accelerazione dello svincolo di Trento Sud", 53, OTHER, ""),
    ("restringimento di carreggiata", 53, OTHER, ""),
    ("cantiere mobile\r\ncarreggiata sud", 52, OTHER, ""),
]


@pytest.mark.parametrize("text, icon, category, access", A22_CASES)
def test_a22_classification(text, icon, category, access):
    o = a22.item_to_ordinanza(_a22(text, icon))
    assert o is not None and o.category == category, text
    assert o.access_kind == access
    assert (o.start_date, o.end_date) == ("2026-11-16", "2026-11-17")


@pytest.mark.parametrize("text, icon", [
    ("area di servizio Paganella ovest non eroga GPL", 11),
    ("area di servizio, erogazione di carburante chiusa\r\nin area di servizio Plose ovest", 11),
    ("Colonnine SOS fuori servizio tra Brennero e Vipiteno", 21),
    ("colonnine di ricarica fuori servizio", 30),
])
def test_a22_service_notices_are_dropped(text, icon):
    assert a22.item_to_ordinanza(_a22(text, icon)) is None and a22.skip_reason(_a22(text, icon))


@pytest.mark.parametrize("km, provinces", [
    ((0, 15.9), ["BZ"]), ((124, 126), ["BZ", "TN"]), ((131.4, 131.4), ["TN"]), ((187.2, 187.2), ["TN"]),
    ((240.8, 240.8), ["VR"]), ((260, 270), ["MN"]), ((298, 299), ["RE"]), ((310, 313), ["MO"]),
])
def test_a22_every_stretch_has_its_province(km, provinces):
    o = a22.item_to_ordinanza(_a22("chiusura carreggiata sud", km=km))
    assert o.provinces == provinces and o.regions


def test_a22_odd_items_never_break_the_list():
    items = [None, "x", {}, {"id": "abc", "titolo": "chiusura"}, {"id": "1", "titolo": ""},
             _a22("chiusura carreggiata sud")]
    assert len(a22.parse_avvisi(items)) == 1


# --- link -------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("x, y, ok", [
    (11.1465074795044, 46.658458877516, True),
    ("11.1465", "46.6584", True),
    (None, None, False), ("", "", False), (0, 0, False),
    (46.65, 11.14, False),        # coordinate scambiate: fuori dall'Italia, meglio nessun link
    ("n.d.", "n.d.", False),
])
def test_wme_link_only_with_good_coordinates(x, y, ok):
    o = bolzano.item_to_ordinanza(_bz("Tratto CHIUSO.", X=x, Y=y))
    url = wme_url(o)
    assert bool(url) == ok
    text = json.dumps(ordinanza_blocks(o), ensure_ascii=False)
    assert ("Apri in WME" in text) == ok and "Apri il bollettino" in text and bolzano.PAGE_URL in text
    if ok:
        assert url.startswith("https://www.waze.com/it/editor?env=row&lat=46.6") and "&lon=11.14" in url


def test_every_message_links_its_source():
    bz = bolzano.item_to_ordinanza(_bz("Tratto CHIUSO."))
    a = a22.item_to_ordinanza(_a22("chiusura carreggiata sud"))
    assert bz.pdf_url == "https://traffico.provincia.bz.it/it/home#tab_text"
    assert a.pdf_url == "https://www.autobrennero.it/it/viabilita/avvisi/"
    assert "Centrale Viabilità Provincia di Bolzano" in json.dumps(ordinanza_blocks(bz), ensure_ascii=False)
    assert "Autostrada del Brennero A22" in json.dumps(ordinanza_blocks(a), ensure_ascii=False)
    assert "CARREGGIATA" in title_line(a22.item_to_ordinanza(_a22("scambio di carreggiata")))


# --- giro: lettura, codifica, avvisi che spariscono e ricompaiono ------------------------------------------

class _Resp:
    def __init__(self, raw: bytes) -> None:
        self.content = raw
        self.text = raw.decode("latin-1")  # come requests quando il server non dichiara il charset


def _run(db, pages: dict[str, bytes], today: date):
    def get(url):
        if url not in pages:
            raise OSError("irraggiungibile")
        return _Resp(pages[url])
    return FontiPoller(db, ["bz", "a22"], get=get).run(today)


def test_accents_survive_with_and_without_bom(tmp_path):
    data = [_bz("Per la manifestazione „Krampuslauf“ a Laives le strade sono CHIUSE; potrà cambiare.")]
    for i, raw in enumerate((json.dumps(data, ensure_ascii=False).encode("utf-8"),
                             b"\xef\xbb\xbf" + json.dumps(data, ensure_ascii=False).encode("utf-8"))):
        db = Database.local(str(tmp_path / f"enc{i}.sqlite3"))
        _run(db, {bolzano.FEED_URL: raw, a22.API_URL: b"[]"}, date(2026, 11, 16))
        o = db.get_ordinanza(ID_OFFSET["bz"] + 31700)
        assert "„Krampuslauf“" in o.excerpt and "potrà" in o.excerpt and "Ã" not in o.excerpt


def test_a_notice_missing_for_one_run_comes_back_without_a_new_message(tmp_path):
    """Se un giro la Provincia pubblica un elenco incompleto, la chiusura viene data per finita; quando
    ricompare torna in vigore con le sue date, senza mandare di nuovo il messaggio."""
    db = Database.local(str(tmp_path / "back.sqlite3"))
    one = json.dumps([_bz("Tratto CHIUSO.", messageId="3170012"), _bz("Altro tratto CHIUSO.", messageId="3170112")]).encode()
    _run(db, {bolzano.FEED_URL: one, a22.API_URL: b"[]"}, date(2026, 11, 16))  # primo giro, in silenzio
    oid = ID_OFFSET["bz"] + 31700
    part = json.dumps([_bz("Altro tratto CHIUSO.", messageId="3170112")]).encode()
    _run(db, {bolzano.FEED_URL: part, a22.API_URL: b"[]"}, date(2026, 11, 17))
    assert db.get_ordinanza(oid).end_date == "2026-11-16"
    r = _run(db, {bolzano.FEED_URL: one, a22.API_URL: b"[]"}, date(2026, 11, 18))
    assert r.new["bz"] == 0 and db.pending_ordinanze() == []
    assert db.get_ordinanza(oid).end_date == "2026-11-30"
    assert any(o.ord_id == oid for o in db.in_force_ordinanze(date(2026, 11, 18)))


def test_a_broken_answer_closes_nothing(tmp_path):
    db = Database.local(str(tmp_path / "broken.sqlite3"))
    one = json.dumps([_bz("Tratto CHIUSO.")]).encode()
    _run(db, {bolzano.FEED_URL: one, a22.API_URL: b"[]"}, date(2026, 11, 16))
    oid = ID_OFFSET["bz"] + 31700
    for bad in (b"", b"<html>manutenzione</html>", b'{"errore": 1}', b"[]"):
        r = _run(db, {bolzano.FEED_URL: bad, a22.API_URL: b"[]"}, date(2026, 11, 17))
        assert db.get_ordinanza(oid).end_date == "2026-11-30", bad
        if bad != b"[]":
            assert "bz" in r.errors


def test_new_closures_are_news_after_the_first_run(tmp_path):
    db = Database.local(str(tmp_path / "news.sqlite3"))
    first = [_bz("Tratto CHIUSO.", messageId="3170012")]
    _run(db, {bolzano.FEED_URL: json.dumps(first).encode(), a22.API_URL: b"[]"}, date(2026, 11, 16))
    more = first + [_bz("Nuovo tratto CHIUSO.", messageId="3170212"), _bz("senso unico alternato", messageId="3170312")]
    a = [_a22("chiusura svincolo in entrata della stazione di Trento Nord", 7, (131.4, 131.4), "sud")]
    r = _run(db, {bolzano.FEED_URL: json.dumps(more).encode(), a22.API_URL: json.dumps(a).encode()},
             date(2026, 11, 16))
    assert r.new == {"bz": 1}  # A22 al primo giro: in silenzio
    assert [o.ord_id for o in db.pending_ordinanze()] == [ID_OFFSET["bz"] + 31702]
