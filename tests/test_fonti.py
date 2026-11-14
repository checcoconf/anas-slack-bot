"""Fonti oltre ANAS: Provincia di Bolzano (RSS) e A22 (JSON), su dati reali del 14/11/2026."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from anas_bot.anas.parser import CLOSURE, OTHER
from anas_bot.db import Database
from anas_bot.fonti import ID_OFFSET, a22, bolzano
from anas_bot.fonti.poller import FAIL_ALERT_RUNS, FontiPoller
from anas_bot.views import ordinanza_blocks, title_line

FIX = Path(__file__).parent / "fixtures"
BZ_XML = (FIX / "bz_feed.xml").read_text(encoding="utf-8")
A22_JSON = (FIX / "a22_avvisi.json").read_text(encoding="utf-8")


def _bz() -> dict[int, object]:
    return {o.ord_id - ID_OFFSET["bz"]: o for o in bolzano.parse_feed(BZ_XML)}


# --- Bolzano -------------------------------------------------------------------------------------------

def test_bz_skips_what_is_not_for_the_map():
    got = _bz()
    assert 5873 not in got       # "Nessuna limitazione"
    assert 5739 not in got       # percorso ciclabile
    assert 5778 not in got       # fuori provincia (Grigioni)
    assert 28788 not in got      # ferrovia
    assert 27227 not in got      # riepilogo generico "Strade di montagna alte e passi:"


def test_bz_same_news_in_two_categories_is_one_notice():
    got = _bz()
    o = got[30717]  # via delle Palade: in "Situazione attuale" (…01) e in "Cantieri" (…12)
    assert sum(1 for k in got if k == 30717) == 1
    assert o.category == CLOSURE
    assert o.roads == ["Comune di Merano"]
    assert (o.km_from, o.km_to) == ("37+150", "37+250")
    assert o.end_date == "2026-11-16" and o.provinces == ["BZ"] and o.regions == ["trentino-alto-adige"]


def test_bz_closures_and_other_notices():
    got = _bz()
    stelvio = got[5871]
    assert stelvio.category == CLOSURE and stelvio.roads == ["SS38"] and stelvio.open_ended
    assert stelvio.start_date == "2026-10-22" and stelvio.km_from == "124+300"
    naturno = got[30575]
    assert naturno.category == CLOSURE and naturno.time_window == "19:00-06:00"
    merano = got[31559]  # "Da martedì 17.11.2026 - ore 00:00: ... CHIUSURA ininterrotta"
    assert merano.category == CLOSURE and merano.start_date == "2026-11-17"
    assert not merano.end_date and not merano.open_ended  # fine non detta: niente "fino a nuova disposizione"
    inaug = got[31611]   # "da sabato 21.11.2026 ... a domenica 22.11.2026"
    assert (inaug.start_date, inaug.end_date) == ("2026-11-21", "2026-11-22")
    # sensi unici alternati, "chiusure temporanee fino a 15 minuti", divieti per categorie: non chiusure
    assert got[28615].category == OTHER and got[28615].roads == ["SP3"]
    assert got[31249].category == OTHER
    assert got[5878].category == OTHER
    assert got[31498].category == OTHER and got[31498].roads == ["SS44"]


# --- A22 -------------------------------------------------------------------------------------------------

def _a22() -> dict[int, object]:
    return {o.ord_id - ID_OFFSET["a22"]: o for o in a22.parse_avvisi(json.loads(A22_JSON))}


def test_a22_service_notices_are_skipped():
    got = _a22()
    assert set(got) == {627438, 622487, 611649}  # niente GPL né colonnine SOS


def test_a22_carriageway_swap_is_a_carriageway_closure():
    o = _a22()[627438]
    assert o.category == CLOSURE and o.ramp_only and o.access_kind == "carreggiata" and not o.uncertain
    assert (o.start_date, o.end_date) == ("2026-11-04", "2026-11-23")
    assert (o.km_from, o.km_to) == ("37+553", "38+674")
    assert o.roads == ["A22"] and o.motorway and o.provinces == ["BZ"]
    assert "nord" in o.direction
    assert "CARREGGIATA CHIUSA" in title_line(o)


def test_a22_deviation_is_a_closure_to_verify():
    o = _a22()[622487]
    assert o.category == CLOSURE and o.uncertain and "deviazione" in o.uncertain_why


def test_a22_provinces_by_km():
    assert a22.provinces_for_km(0, 15.9) == ["BZ"]
    assert a22.provinces_for_km(120, 130) == ["BZ", "TN"]
    assert a22.provinces_for_km(240.8, 240.8) == ["VR"]
    assert a22.provinces_for_km(310, 313) == ["MO"]


def test_a22_unexpected_answer_is_an_error():
    with pytest.raises(ValueError):
        a22.parse_avvisi({"errore": "manutenzione"})


# --- messaggi ------------------------------------------------------------------------------------------

def test_messages_name_the_source_and_link_the_page():
    o = _bz()[30717]
    blocks = ordinanza_blocks(o)
    text = json.dumps(blocks, ensure_ascii=False)
    assert "Centrale Viabilità Provincia di Bolzano" in text and "Apri il bollettino" in text
    assert "Ordinanza" not in blocks[1]["elements"][0]["text"]


# --- giro ------------------------------------------------------------------------------------------------

class _Resp:
    def __init__(self, text: str) -> None:
        self.text = text


def _poller(db, pages: dict[str, str]):
    def get(url: str):
        if url not in pages:
            raise OSError("irraggiungibile")
        return _Resp(pages[url])
    return FontiPoller(db, ["bz", "a22"], get=get)


def test_first_run_is_silent_then_only_news(tmp_path):
    db = Database.local(str(tmp_path / "f.sqlite3"))
    pages = {bolzano.FEED_URL: BZ_XML, a22.API_URL: A22_JSON}
    r = _poller(db, pages).run(date(2026, 11, 14))
    assert r.new == {} and r.silent["bz"] > 0 and r.silent["a22"] == 3
    assert db.pending_ordinanze() == []  # niente valanga al primo giro

    # una chiusura nuova nel feed: solo quella è una novità
    extra = ('<item><title>SS12 dell\'Abetone e del Brennero</title><guid isPermaLink="false">3170012</guid>'
             '<description>A Laives (km 420,100 - km 420,300) CHIUSURA al traffico dalle ore 21:00 alle ore 05:00 '
             'per lavori.</description><category>Cantieri stradali / Chiusure</category>'
             '<pubDate>Mon, 16 Nov 2026 00:00:00 GMT</pubDate></item>')
    pages[bolzano.FEED_URL] = BZ_XML.replace("</channel>", extra + "</channel>")
    r = _poller(db, pages).run(date(2026, 11, 14))
    assert r.new == {"bz": 1, "a22": 0}
    pending = db.pending_ordinanze()
    assert [o.ord_id for o in pending] == [ID_OFFSET["bz"] + 31700]
    assert pending[0].category == CLOSURE and pending[0].time_window == "21:00-05:00"


def test_a_broken_source_never_stops_the_others_and_alerts_once(tmp_path):
    db = Database.local(str(tmp_path / "g.sqlite3"))
    pages = {bolzano.FEED_URL: BZ_XML}  # A22 irraggiungibile
    alerts = []
    for _ in range(FAIL_ALERT_RUNS + 1):
        r = _poller(db, pages).run(date(2026, 11, 14))
        alerts += r.alerts
        assert "a22" in r.errors and "bz" not in r.errors
    assert len(alerts) == 1 and "Autostrada del Brennero" in alerts[0]
    pages[a22.API_URL] = A22_JSON
    r = _poller(db, pages).run(date(2026, 11, 14))
    assert any("di nuovo leggibile" in a for a in r.alerts)


def test_sources_setting():
    from anas_bot.config import Config
    c = Config()
    assert c.enabled_sources() == ["bz", "a22"]
    c.fonti = "no"
    assert c.enabled_sources() == []
    c.fonti = "a22"
    assert c.enabled_sources() == ["a22"]


def test_no_end_date_is_not_shown_as_until_further_notice():
    got = _bz()
    text = json.dumps(ordinanza_blocks(got[31559]), ensure_ascii=False)
    assert "fine non indicata" in text and "nuova disposizione" not in text
    winter = json.dumps(ordinanza_blocks(got[5871]), ensure_ascii=False)  # passo dello Stelvio d'inverno
    assert "nuova disposizione" in winter


def test_notices_removed_by_the_source_are_closed(tmp_path):
    db = Database.local(str(tmp_path / "h.sqlite3"))
    pages = {bolzano.FEED_URL: BZ_XML, a22.API_URL: A22_JSON}
    _poller(db, pages).run(date(2026, 11, 14))
    naturno = ID_OFFSET["bz"] + 30575
    assert any(o.ord_id == naturno for o in db.in_force_ordinanze(date(2026, 11, 18)))
    # la galleria di Naturno sparisce dal bollettino: lavori finiti
    start = BZ_XML.index("<item><title>SS38 Strada statale Val Venosta")
    stop = BZ_XML.index("</item>", start) + len("</item>")
    pages[bolzano.FEED_URL] = BZ_XML[:start] + BZ_XML[stop:]
    _poller(db, pages).run(date(2026, 11, 18))
    assert db.get_ordinanza(naturno).end_date == "2026-11-17"
    assert not any(o.ord_id == naturno for o in db.in_force_ordinanze(date(2026, 11, 18)))
    # una risposta vuota (guasto della fonte) non chiude niente
    pages[a22.API_URL] = "[]"
    _poller(db, pages).run(date(2026, 11, 18))
    assert db.get_ordinanza(ID_OFFSET["a22"] + 627438).end_date == "2026-11-23"
