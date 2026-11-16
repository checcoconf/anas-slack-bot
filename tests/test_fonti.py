"""Fonti oltre ANAS: Provincia di Bolzano (JSON del bollettino) e A22 (JSON), su dati reali del 14/11/2026."""

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
BZ_JSON = (FIX / "bz_traffic.json").read_text(encoding="utf-8")
A22_JSON = (FIX / "a22_avvisi.json").read_text(encoding="utf-8")


def _bz() -> dict[int, object]:
    return {o.ord_id - ID_OFFSET["bz"]: o for o in bolzano.parse_traffic(json.loads(BZ_JSON))}


def _bz_with(*extra: dict) -> str:
    return json.dumps(json.loads(BZ_JSON) + list(extra), ensure_ascii=False)


# --- Bolzano -------------------------------------------------------------------------------------------

def test_bz_only_closures():
    """Solo chiusure: cantieri e sensi unici la Provincia li inserisce già da sé in Waze (indicazione dello SM)."""
    got = _bz()
    assert set(got) == {29025, 30717, 31559, 30575, 31611, 30351, 6098, 5871, 31385}
    assert all(o.category == CLOSURE for o in got.values())
    # scartati: "Nessuna limitazione" (6853), riepilogo "Strade di montagna alte e passi:" (27227), ferrovia
    # (28788), funicolare (27316), Austria (30675), SS42 Mendola-Ronzone fuori Alto Adige (31601), pista
    # ciclabile (27200), sensi unici alternati e "chiusure temporanee di 10 minuti" (27428, 28829, 28493),
    # divieto per autobus e mezzi pesanti (5877)


def test_bz_same_news_in_two_categories_is_one_notice():
    o = _bz()[30717]  # via delle Palade: in "Situazione attuale" (…01) e in "Cantieri" (…12)
    assert o.roads == ["Comune di Merano"]
    assert (o.km_from, o.km_to) == ("37+150", "37+250")
    assert (o.start_date, o.end_date) == ("2026-11-06", "2026-11-16")
    assert o.provinces == ["BZ"] and o.regions == ["trentino-alto-adige"]


def test_bz_dates_roads_and_hours():
    got = _bz()
    stelvio = got[5871]
    assert stelvio.roads == ["SS38"] and stelvio.road_names == {"SS38": "Passo dello Stelvio"}
    assert stelvio.open_ended and not stelvio.end_date and stelvio.start_date == "2026-10-22"
    assert stelvio.km_from == "124+300" and stelvio.excerpt.startswith("Chiusura invernale.")
    assert got[6098].roads == ["SS44bis"]
    assert got[29025].roads == ["SP104"] and got[29025].road_names == {"SP104": "Laudes"}
    naturno = got[30575]
    assert naturno.time_window == "19:00-06:00" and (naturno.start_date, naturno.end_date) == ("2026-11-17", "2026-11-18")
    # il bollettino mette l'inizio il giorno prima; vale la data del testo
    assert got[31559].start_date == "2026-11-17"    # beginDate 16/11, "Da martedì 17.11.2026 - ore 00:00"
    assert (got[31611].start_date, got[31611].end_date) == ("2026-11-21", "2026-11-22")  # beginDate 20/11
    assert got[29025].start_date == "2026-11-13"    # "da venerdì 13.11.2026": coincide con beginDate
    luson = got[31385]  # chiusa per maltempo, fine non detta: niente "fino a nuova disposizione"
    assert not luson.end_date and not luson.open_ended
    assert got[30351].excerpt.startswith("Per la manifestazione „Krampuslauf“")  # UTF-8 intatto


def test_bz_start_date_from_the_text():
    """16/11/2026, SP43 Passo Furcia: beginDate 17/11 ma "Da mercoledì 18.11.2026: ... CHIUSURA"."""
    o = bolzano.item_to_ordinanza({
        "messageId": "3170512", "beginDate": "2026-11-17", "endDate": "2026-11-20", "messageGradId": "3",
        "messageTypeId": "12", "messageZoneId": "7", "messageStreetNr": "LS/SP43", "messageStreetInternetDescIt": "Passo Furcia",
        "placeIt": "Da mercoledì 18.11.2026: Nei pressi del Passo Furcia (km 10,850 – km 11,150) CHIUSURA al traffico "
                   "per la realizzazione di sottopassi stradali."})
    assert (o.start_date, o.end_date) == ("2026-11-18", "2026-11-20") and o.roads == ["SP43"]


def test_bz_closures_written_in_other_ways():
    """16/11/2026: "vengono CHIUSI" (plurale maschile) e una chiusura per incidente con grado 4 ("rallentamenti")."""
    base = {"beginDate": "2026-11-16", "endDate": "2026-11-29", "messageTypeId": "1", "messageZoneId": "4",
            "messageStreetNr": "", "messageStreetInternetDescIt": "Comune di Bolzano"}
    calcio = bolzano.item_to_ordinanza(base | {"messageId": "635901", "messageGradId": "3", "placeIt":
        "Per la partita di calcio del F.C. Südtirol viale Trieste e via Trento vengono CHIUSI al traffico dalle ore 12:00"})
    brunico = bolzano.item_to_ordinanza(base | {"messageId": "2779312", "messageGradId": "4", "messageStreetNr": "SS49",
        "messageStreetInternetDescIt": "della Pusteria", "placeIt": "A Brunico (km 0,500 - km 1,000) CHIUSURA dopo un incidente"})
    assert calcio.category == CLOSURE and brunico.category == CLOSURE
    libero = bolzano.item_to_ordinanza(base | {"messageId": "685308", "messageGradId": "5", "placeIt": "Nessuna limitazione."})
    assert libero is None


def test_bz_unexpected_answer_is_an_error():
    with pytest.raises(ValueError):
        bolzano.parse_traffic({"errore": "manutenzione"})


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


def test_a22_deviation_with_traffic_left_on_the_carriageway_is_not_a_closure():
    """16/11/2026: la carreggiata sud resta aperta con 2 corsie per chi non è deviato: per Waze non è una chiusura."""
    o = a22.item_to_ordinanza({
        "id": "632001", "codiceIcona": 54, "kM_Inizio": 8.817, "kM_Fine": 12.049, "direzione": "sud",
        "titolo": "Dalle ore 08:00 del 11/11/2026 alle ore 14:00 del 20/11/2026\r\ndeviazione di carreggiata con "
                  "2 corsie per il traffico non deviato\r\ndal km 8.817 al km 12.049 tra Brennero Paese e "
                  "Vipiteno\r\ncarreggiata sud"})
    assert o.category == OTHER and not o.ramp_only and not o.uncertain
    assert (o.start_date, o.end_date) == ("2026-11-11", "2026-11-20") and o.provinces == ["BZ"]


def test_a22_whole_service_area_closed_but_not_just_fuel():
    """16/11/2026: "area di servizio chiusa" è una chiusura (icona 11 come il GPL); il solo carburante no."""
    area = a22.item_to_ordinanza({"id": "628969", "codiceIcona": 11, "kM_Inizio": 187.2, "kM_Fine": 187.2,
        "direzione": "sud", "titolo": "Dalle ore 22:00 del 16/11/2026 alle ore 18:00 del 19/11/2026 - area di servizio "
                                       "chiusa\r\nper lavori di manutenzione\r\nin area di servizio Adige ovest\r\ncarreggiata sud"})
    assert area.category == CLOSURE and area.access_kind == "area di servizio" and area.provinces == ["TN"]
    assert "AREA DI SERVIZIO CHIUSA" in title_line(area)
    fuel = a22.item_to_ordinanza({"id": "629495", "codiceIcona": 11, "kM_Inizio": 41.8, "kM_Fine": 41.8,
        "direzione": "sud", "titolo": "Dalle ore 10:21 del 16/11/2026 - area di servizio, erogazione di carburante "
                                       "chiusa\r\nper lavori in corso\r\nin area di servizio Plose ovest\r\ncarreggiata sud"})
    assert fuel is None
    svincolo = a22.item_to_ordinanza({"id": "628430", "codiceIcona": 7, "kM_Inizio": 131.4, "kM_Fine": 131.4,
        "direzione": "sud", "titolo": "Dalle ore 20:00 del 16/11/2026 alle ore 06:00 del 17/11/2026\r\nchiusura svincolo "
                                       "in entrata\r\ndella stazione autostradale di Trento Nord\r\ncarreggiata sud"})
    assert svincolo.category == CLOSURE and svincolo.access_kind == "svincolo" and svincolo.provinces == ["TN"]


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
    # link a WME sul punto della chiusura (coordinate del bollettino)
    assert "waze.com/it/editor?env=row&lat=46.658459&lon=11.146507&zoomLevel=18|📍 Apri in WME" in text
    assert "Apri in WME" not in json.dumps(ordinanza_blocks(_a22()[627438]), ensure_ascii=False)  # A22: niente coordinate


def test_the_zone_form_explains_alto_adige_sources():
    from anas_bot.views import preferences_modal
    text = json.dumps(preferences_modal(None), ensure_ascii=False)
    assert "Provincia di Bolzano e Autostrada del Brennero (A22)" in text and bolzano.PAGE_URL in text and a22.PAGE_URL in text


# --- giro ------------------------------------------------------------------------------------------------

class _Resp:
    """Come requests senza charset dichiarato: .text decodificato in latin-1, .content i byte veri."""
    def __init__(self, text: str) -> None:
        self.content = text.encode("utf-8")
        self.text = self.content.decode("latin-1")


def _poller(db, pages: dict[str, str]):
    def get(url: str):
        if url not in pages:
            raise OSError("irraggiungibile")
        return _Resp(pages[url])
    return FontiPoller(db, ["bz", "a22"], get=get)


def test_first_run_is_silent_then_only_news(tmp_path):
    db = Database.local(str(tmp_path / "f.sqlite3"))
    pages = {bolzano.FEED_URL: BZ_JSON, a22.API_URL: A22_JSON}
    r = _poller(db, pages).run(date(2026, 11, 14))
    assert r.new == {} and r.silent["bz"] > 0 and r.silent["a22"] == 3
    assert db.pending_ordinanze() == []  # niente valanga al primo giro

    # una chiusura nuova nel bollettino: solo quella è una novità
    pages[bolzano.FEED_URL] = _bz_with(
        {"messageId": "3170012", "beginDate": "2026-11-16", "endDate": "2026-11-17", "messageGradId": "3",
         "messageTypeId": "12", "messageZoneId": "4", "messageStreetNr": "SS12",
         "messageStreetInternetDescIt": "dell'Abetone e del Brennero",
         "placeIt": "A Laives (km 420,100 - km 420,300) CHIUSURA al traffico dalle ore 21:00 alle ore 05:00 per lavori."})
    r = _poller(db, pages).run(date(2026, 11, 14))
    assert r.new == {"bz": 1, "a22": 0}
    pending = db.pending_ordinanze()
    assert [o.ord_id for o in pending] == [ID_OFFSET["bz"] + 31700]
    assert pending[0].category == CLOSURE and pending[0].time_window == "21:00-05:00"


def test_a_broken_source_never_stops_the_others_and_alerts_once(tmp_path):
    db = Database.local(str(tmp_path / "g.sqlite3"))
    pages = {bolzano.FEED_URL: BZ_JSON}  # A22 irraggiungibile
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
    text = json.dumps(ordinanza_blocks(got[31385]), ensure_ascii=False)
    assert "fine non indicata" in text and "nuova disposizione" not in text
    winter = json.dumps(ordinanza_blocks(got[5871]), ensure_ascii=False)  # passo dello Stelvio d'inverno
    assert "nuova disposizione" in winter


def test_notices_removed_by_the_source_are_closed(tmp_path):
    db = Database.local(str(tmp_path / "h.sqlite3"))
    pages = {bolzano.FEED_URL: BZ_JSON, a22.API_URL: A22_JSON}
    _poller(db, pages).run(date(2026, 11, 14))
    naturno = ID_OFFSET["bz"] + 30575
    assert any(o.ord_id == naturno for o in db.in_force_ordinanze(date(2026, 11, 18)))
    # la galleria di Naturno sparisce dal bollettino: lavori finiti
    pages[bolzano.FEED_URL] = json.dumps([x for x in json.loads(BZ_JSON) if x["messageId"][:-2] != "30575"])
    _poller(db, pages).run(date(2026, 11, 18))
    assert db.get_ordinanza(naturno).end_date == "2026-11-17"
    assert not any(o.ord_id == naturno for o in db.in_force_ordinanze(date(2026, 11, 18)))
    # una risposta vuota (guasto della fonte) non chiude niente
    pages[a22.API_URL] = "[]"
    _poller(db, pages).run(date(2026, 11, 18))
    assert db.get_ordinanza(ID_OFFSET["a22"] + 627438).end_date == "2026-11-23"


def test_many_notices_respect_the_d1_variable_limit(tmp_path):
    """14/11/2026, primo giro reale: ~120 avvisi di Bolzano in un solo IN (...) e Cloudflare D1 rifiuta
    ("too many SQL variables", max 100). Qui un database che rifiuta come D1 e un bollettino da 250 chiusure."""
    from anas_bot.db import LocalSqlite

    class LikeD1(LocalSqlite):
        def query(self, sql, params=()):
            assert len(params) <= 100, f"query con {len(params)} variabili"
            return super().query(sql, params)

        def batch(self, stmts):
            for _, params in stmts:
                assert len(params) <= 100
            return super().batch(stmts)

    db = Database(LikeD1(str(tmp_path / "d1.sqlite3")))
    feed = _bz_with(*({"messageId": str(4000000 + i * 100 + 12), "beginDate": "2026-11-16", "endDate": "2026-11-30",
                       "messageGradId": "3", "messageTypeId": "12", "messageZoneId": "4", "messageStreetNr": "SS12",
                       "messageStreetInternetDescIt": "dell'Abetone e del Brennero",
                       "placeIt": f"A Laives (km {i},100 - km {i},300) CHIUSURA al traffico per lavori."}
                      for i in range(250)))
    r = _poller(db, {bolzano.FEED_URL: feed, a22.API_URL: A22_JSON}).run(date(2026, 11, 14))
    assert r.errors == {} and r.silent["bz"] > 250 and r.silent["a22"] == 3
    r = _poller(db, {bolzano.FEED_URL: feed, a22.API_URL: A22_JSON}).run(date(2026, 11, 14))
    assert r.errors == {} and r.new == {"bz": 0, "a22": 0}
    assert len(db.get_ordinanze([ID_OFFSET["bz"] + 40000 + i for i in range(250)])) == 250


def test_bolzano_is_read_only_while_the_bulletin_is_updated(tmp_path):
    from datetime import datetime
    assert bolzano.is_updated_now(datetime(2026, 11, 14, 6, 5))       # sabato, 6:05
    assert bolzano.is_updated_now(datetime(2026, 11, 14, 20, 40))      # dopo l'ultimo aggiornamento delle 20
    assert not bolzano.is_updated_now(datetime(2026, 11, 14, 21, 5))
    assert not bolzano.is_updated_now(datetime(2026, 11, 15, 7, 5))    # domenica: dalle 8
    assert bolzano.is_updated_now(datetime(2026, 11, 15, 8, 5))
    db = Database.local(str(tmp_path / "n.sqlite3"))
    asked = []

    def get(url):
        asked.append(url)
        return _Resp(BZ_JSON if url == bolzano.FEED_URL else A22_JSON)
    FontiPoller(db, ["bz", "a22"], get=get).run(date(2026, 11, 14), datetime(2026, 11, 14, 2, 5))
    assert asked == [a22.API_URL]  # di notte solo l'A22, che pubblica a ogni ora


def test_changed_notices_are_updated_without_a_new_message(tmp_path):
    db = Database.local(str(tmp_path / "u.sqlite3"))
    pages = {bolzano.FEED_URL: BZ_JSON, a22.API_URL: A22_JSON}
    _poller(db, pages).run(date(2026, 11, 14))
    # la Provincia sposta la fine della galleria di Naturno: dati aggiornati, nessun nuovo messaggio
    data = json.loads(BZ_JSON)
    for x in data:
        if x["messageId"][:-2] == "30575":
            x["endDate"] = "2026-11-25"
    pages[bolzano.FEED_URL] = json.dumps(data, ensure_ascii=False)
    r = _poller(db, pages).run(date(2026, 11, 15))
    assert r.new == {"bz": 0, "a22": 0} and db.pending_ordinanze() == []
    assert db.get_ordinanza(ID_OFFSET["bz"] + 30575).end_date == "2026-11-25"

