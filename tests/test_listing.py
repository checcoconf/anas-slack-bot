"""Elenco ufficiale: classificazione su ordinanze VERE di ANAS e giro completo con un elenco finto."""

import copy
import json
from datetime import date
from pathlib import Path

import pytest

from anas_bot.anas.listing import ITALY, STRUCTURE_REGIONS, Structure, everyone, parse_structures, record_to_ordinanza
from anas_bot.anas.parser import CLOSURE, OTHER, parse_ordinanza
from anas_bot.anas.vocabolario import KNOWN_MEASURES, unknown_measures
from anas_bot.anas.client import BlockedError, TransientError
from anas_bot.config import Config
from anas_bot.db import Database
from anas_bot.geo import REGIONS
from anas_bot.listing_poller import ListingPoller
from tests import samples as s
from tests.fakes import FakeSource

FIX = Path(__file__).parent / "fixtures"
BARI = json.loads((FIX / "searchordinanze_BA_p1.json").read_text(encoding="utf-8"))
BY_ID = {r["ID"]: r for r in BARI["results"]}
REALI = json.loads((FIX / "ordinanze_reali.json").read_text(encoding="utf-8"))


def _rec(id_, riepilogo, causa_dett="Completamento, ammodernamento, potenziamento strada", tipo="Ordinaria",
         numero="900/2026/BA"):
    return {"ID": str(id_), "TIPO_ORDINANZA": tipo, "NUMERO_ORDINANZA": numero, "COMPARTIMENTO": "Bari",
            "CAUSA": "Cantiere", "CAUSA_DETT": causa_dett, "RIEPILOGO": riepilogo, "PROROGA_DATA": ""}


def _riep(tratta, lanes, measures, period, users="tutti  gli utenti"):
    lis = "".join(f"<li>{m}</li>" for m in measures)
    return (f"L'Ordinanza sar&agrave; applicata alla tratta <strong>{tratta}</strong> {lanes} attuando i seguenti "
            f"provvedimenti:<br> <ul>{lis}</ul> {period}<br> Interesser&agrave;: {users}<br><br>")


# --- ordinanze vere (collaudo del 02/11/2026) --------------------------------------

@pytest.mark.parametrize("case", REALI, ids=[c["record"]["ID"] for c in REALI])
def test_real_ordinances(case):
    rec = case["record"]
    o = record_to_ordinanza(rec, rec.get("struttura_nome", ""), "u")
    got = o.category if o else "serve PDF"
    assert got == case["atteso"], case["perche"]


def test_real_details():
    by = {c["record"]["ID"]: c["record"] for c in REALI}
    o = record_to_ordinanza(by["129585"], "Lombardia", "u")
    assert o.speeds == [70, 90] and o.roads[0] == "SS36"
    o = record_to_ordinanza(by["147610"], "Cagliari", "u")
    assert o.new_road and o.regions == ["sardegna"]
    o = record_to_ordinanza(by["33080"], "Ancona", "u")
    assert o.ramp_only
    o = record_to_ordinanza(by["209395"], "Autostrada del Mediterraneo", "u")
    assert o.regions == ["basilicata", "calabria", "campania"] and o.end_date == "2026-12-31"
    o = record_to_ordinanza(by["36010"], "Sassari", "u")
    assert not o.excerpt.lower().startswith("l'ordinanza")


def test_real_bari_page():
    assert record_to_ordinanza(BY_ID["213347"], "Puglia", "u").category == OTHER  # 40 km/h di cantiere
    assert record_to_ordinanza(BY_ID["213490"], "Puglia", "u").category == OTHER  # deviazione, nessuna chiusura
    o = record_to_ordinanza(BY_ID["213281"], "Puglia", "u")
    assert o.category == OTHER and o.time_window == "20:30-06:00" and o.road_names["SS16"] == "Adriatica"
    o = record_to_ordinanza(BY_ID["213347"], "Puglia", "u")
    assert o.roads == ["SS613"] and o.road_names["SS613"] == "Brindisi - Lecce"
    assert (o.km_from, o.km_to, o.start_date, o.end_date) == ("19+000", "22+315", "2026-11-02", "2026-12-18")
    assert record_to_ordinanza(BY_ID["213467"], "Puglia", "u") is None  # proroga: serve il PDF


def test_vocabulary_covers_real_measures():
    assert len(KNOWN_MEASURES) == 77
    assert unknown_measures(["chiusura al traffico", "limite di velocita 40Km/h".lower()]) == []
    assert unknown_measures(["chiusura notturna a targhe alterne"]) == ["chiusura notturna a targhe alterne"]


@pytest.mark.parametrize("users,expected", [
    ("tutti gli utenti", True), ("tutti gli autoveicoli", True), ("tutti tranne mezzi di soccorso", True),
    ("tutti tranne traffico locale l'ordinanza sara", True), ("; tutti ; tutti veicoli aventi massa superiore a 26t", True),
    ("tutti veicoli aventi massa superiore a 44t", False), ("tutti gli autoveicoli veicoli aventi massa superiore a 44t", False),
    ("autocarri", False), ("; pedoni ; velocipedi", False), ("veicoli che trasportano merci pericolose", False),
])
def test_everyone(users, expected):
    assert everyone(users) is expected


# --- casi sintetici nello stesso formato ------------------------------------------------

def test_ramp_closure_synthetic():
    r = _rec(2, _riep("SS 16 ADRIATICA", "al km <strong>704+500</strong> sulla <strong>rampa di uscita</strong>,",
                      ["chiusura al traffico"], "a partire dal <strong>05/11/2026</strong> fino al <strong>06/11/2026</strong>"))
    o = record_to_ordinanza(r, "Puglia", "u")
    assert o.category == CLOSURE and o.ramp_only and o.km_from == "704+500"


def test_closure_with_night_window():
    r = _rec(1, _riep("SS 16 ADRIATICA", "dal km <strong>700+000</strong> al km <strong>702+000</strong> su "
                      "<strong>tutte le corsie</strong>,", ["chiusura al traffico"],
                      "a partire dal <strong>05/11/2026</strong> fino al <strong>06/11/2026</strong> nella fascia "
                      "oraria dalle <strong>22:00</strong> alle <strong>06:00</strong> del giorno successivo"))
    o = record_to_ordinanza(r, "Puglia", "u")
    assert o.category == CLOSURE and not o.ramp_only and o.time_window == "22:00-06:00"


def test_speed_limit_of_worksite_cause_is_not_permanent():
    r = _rec(5, _riep("SS 100", "su <strong>tutte le corsie</strong>,", ["limite di velocita 50Km/h"],
                      "a partire dal <strong>15/11/2026</strong>"), causa_dett="Frana/Smottamento")
    assert record_to_ordinanza(r, "Puglia", "u").category == OTHER


def test_structure_menu_parsing():
    page = """<select name="area_compartimentale" id="edit-area"><option value="*">- Qualsiasi -</option>
    <option value="BA">Puglia</option><option value="MI">Lombardia</option></select>
    <select name="causa"><option value="*">- Qualsiasi -</option><option value="C1">Cantiere</option></select>"""
    assert parse_structures(page) == [Structure("BA", "Puglia"), Structure("MI", "Lombardia")]


def test_every_structure_has_regions_and_all_anas_regions_are_covered():
    covered = {r for rs in STRUCTURE_REGIONS.values() for r in rs}
    assert covered == set(REGIONS) - {"trentino-alto-adige"}  # nessuna strada ANAS in Trentino-Alto Adige


# --- giro completo con un elenco finto ------------------------------------------------------

def _closure(id_, start, end="30/11/2026", numero="900/2026/BA"):
    return _rec(id_, _riep("SS 16", "su <strong>tutte le corsie</strong>,", ["chiusura al traffico"],
                           f"a partire dal <strong>{start}</strong> fino al <strong>{end}</strong>"), numero=numero)


class FakeListing:
    """Elenco finto: 5 risultati per pagina, le ordinanze in cima alla lista sono le più recenti.

    La ricerca "tutta Italia" ("*") alterna le strutture partendo dalla cima di ciascuna: come sul
    sito vero, ciò che viene inserito in testa (insert(0, ...)) è "appena pubblicato" e sta in prima
    pagina, ciò che viene aggiunto in coda (append) sta in fondo."""

    def __init__(self, pages: dict[str, list[dict]]):
        self.pages = pages
        self.calls: list[tuple[str, int]] = []
        self.last_total_records = 0

    def structures(self, day=None):
        return [Structure(c, {"BA": "Puglia", "MI": "Lombardia"}[c]) for c in self.pages]

    def _italy(self) -> list[dict]:
        out, i = [], 0
        while any(i < len(recs) for recs in self.pages.values()):
            out.extend(recs[i] for recs in self.pages.values() if i < len(recs))
            i += 1
        return out

    def search_page(self, code, day, page, causa="*", causa_dett="*"):
        self.calls.append((code, page))
        recs = self._italy() if code == ITALY else self.pages[code]
        if causa != "*":
            recs = [r for r in recs if r.get("CAUSA") == causa]
        return {"tot_pagine": (len(recs) + 4) // 5, "tot_record": len(recs),
                "results": copy.deepcopy(recs[(page - 1) * 5: page * 5])}

    def iter_structure(self, code, day):
        self.calls.append((code, 0))  # 0 = lettura completa
        self.last_total_records = len(self.pages[code])
        return iter(copy.deepcopy(self.pages[code]))


@pytest.fixture
def env(tmp_path):
    cfg = Config()
    db = Database.local(str(tmp_path / "l.sqlite3"))
    old = [_closure(300 + i, "20/10/2026") for i in range(12)]  # chiusure già in vigore prima del bot
    pages = {"BA": [*BARI["results"], *old], "MI": [_closure(500, "01/09/2026", numero="10/2026/MI")]}
    pdfs = {213467: s.EXTENSION_BARI, 213466: s.LANE_ONLY}
    return cfg, db, FakeListing(pages), FakeSource(pdfs)


def _install(p, listing):
    """Primo giro: legge le prime pagine della ricerca "tutta Italia" e segna tutto come già visto."""
    p.run(date(2026, 11, 1))


def test_old_ordinances_are_never_notified(env):
    cfg, db, listing, src = env
    _install(ListingPoller(db, listing, src, cfg), listing)
    assert db.pending_ordinanze() == []                 # 13 chiusure vecchie: nessuna in coda
    assert src.requests == []                           # e nessun PDF scaricato per le vecchie


def test_new_closure_at_top_of_list_is_notified_next_run(env):
    cfg, db, listing, src = env
    p = ListingPoller(db, listing, src, cfg)
    _install(p, listing)
    listing.pages["MI"].insert(0, _closure(212000, "03/11/2026", numero="11/2026/MI"))  # numero BASSO
    r = p.run(date(2026, 11, 2))
    assert r.new == 1 and r.relevant == 1
    assert [o.ord_id for o in db.pending_ordinanze()] == [212000]
    assert ("MI", 1) in listing.calls                   # trovata dalla lettura veloce della prima pagina


def test_fast_scan_reads_few_pages_when_nothing_is_new(env):
    cfg, db, listing, src = env
    p = ListingPoller(db, listing, src, cfg)
    _install(p, listing)
    listing.calls.clear()
    p.run(date(2026, 11, 2))
    fast = [c for c in listing.calls if c[1] > 0]
    assert fast == [("BA", 1), ("MI", 1)]               # niente di nuovo: solo la prima pagina


def test_closure_starting_from_install_day_is_notified_during_first_scan(env):
    cfg, db, listing, src = env
    listing.pages["BA"].insert(0, _closure(400, "01/11/2026", "03/11/2026"))
    ListingPoller(db, listing, src, cfg).run(date(2026, 11, 1))
    assert [o.ord_id for o in db.pending_ordinanze()] == [400]


def test_number_channel_restarts_from_newest_listing_id(env):
    """Se un giorno l'elenco non si legge, il canale a numeri deve cercare solo le ordinanze nuove."""
    cfg, db, listing, src = env
    _install(ListingPoller(db, listing, src, cfg), listing)
    assert db.cursor() == max(int(r["ID"]) for recs in listing.pages.values() for r in recs)


def test_extension_inherits_from_original_closure(env, monkeypatch):
    cfg, db, listing, src = env
    p = ListingPoller(db, listing, src, cfg)
    _install(p, listing)
    # nel PDF della proroga si cita l'ordinanza originale 900/2026/BA (una chiusura già vista)
    # ID alto: pubblicata dopo l'installazione (sotto l'ID "spartiacque" del primo giro è tutto vecchio)
    src.docs[213700] = "ORDINANZA N°950/2026/BA\\nORDINA la proroga dell'ordinanza n. 900/2026/BA fino al 15/12/2026"
    proroga = {"ID": "213700", "TIPO_ORDINANZA": "Proroga", "NUMERO_ORDINANZA": "950/2026/BA", "COMPARTIMENTO": "Bari",
               "CAUSA": "Cantiere", "CAUSA_DETT": "", "RIEPILOGO": "", "PROROGA_DATA": "15/12/2026"}
    listing.pages["BA"].insert(0, proroga)
    p.run(date(2026, 11, 2))
    o = db.get_ordinanza(213700)
    assert o.category == CLOSURE and o.extension and o.end_date == "2026-12-15" and o.roads == ["SS16"]
    assert o.number == "950/2026/BA"


REAL_PROROGA = (Path(__file__).parent / "fixtures" / "proroga_621_2026_UC.txt").read_text(encoding="utf-8")


def test_real_proroga_pdf_number_and_reference():
    """PDF reale 213628: proroga 621/2026/UC dell'ordinanza 459/2026/UC (A2, restringimento)."""
    o = parse_ordinanza(213628, REAL_PROROGA, "u")
    assert o.number == "621/2026/UC"        # il suo numero, non quello dell'ordinanza citata
    assert o.provinces == ["CZ"]


def test_real_proroga_of_lane_restriction_is_not_notified(env):
    """La proroga di un restringimento resta un restringimento, anche se il PDF parla di chiusura di corsia."""
    cfg, db, listing, src = env
    original = _rec(950, _riep("A2 AUTOSTRADA DEL MEDITERRANEO", "carreggiata Nord,", ["restringimento carreggiata"],
                               "a partire dal <strong>04/09/2026</strong> fino al <strong>31/10/2026</strong>"),
                    numero="459/2026/UC")
    listing.pages["BA"].insert(0, original)
    p = ListingPoller(db, listing, src, cfg)
    _install(p, listing)
    src.docs[213628] = REAL_PROROGA
    listing.pages["BA"].insert(0, {"ID": "213628", "TIPO_ORDINANZA": "Proroga", "NUMERO_ORDINANZA": "621/2026/UC",
                                   "COMPARTIMENTO": "Autostrada del Mediterraneo", "CAUSA": "Cantiere",
                                   "CAUSA_DETT": "Gestione opere di sicurezza", "RIEPILOGO": "",
                                   "PROROGA_DATA": "30/11/2026"})
    r = p.run(date(2026, 11, 2))
    o = db.get_ordinanza(213628)
    assert r.new == 1 and r.relevant == 0 and db.pending_ordinanze() == []
    assert o.category == OTHER and o.extension and o.end_date == "2026-11-30" and o.number == "621/2026/UC"


def test_listing_upgrades_ordinance_misclassified_by_number_channel(env):
    cfg, db, listing, src = env
    p = ListingPoller(db, listing, src, cfg)
    _install(p, listing)
    from anas_bot.anas.parser import parse_ordinanza
    db.save_ordinanza(parse_ordinanza(555, s.LANE_ONLY), "")    # canale a numeri: "altro"
    listing.pages["BA"].insert(0, _closure(555, "03/11/2026"))
    r = p.run(date(2026, 11, 2))
    assert r.upgraded == 1 and [o.ord_id for o in db.pending_ordinanze()] == [555]


def test_unknown_measures_are_reported(env):
    cfg, db, listing, src = env
    p = ListingPoller(db, listing, src, cfg)
    _install(p, listing)
    listing.pages["MI"].insert(0, _rec(600, _riep("SS 36", "su <strong>tutte le corsie</strong>,",
                                                   ["chiusura a targhe alterne"], "a partire dal 03/11/2026")))
    r = p.run(date(2026, 11, 2))
    assert list(r.unknown) == ["chiusura a targhe alterne"] and "ord_id=" in r.unknown["chiusura a targhe alterne"]


def test_known_structures_used_when_menu_is_built_by_javascript(monkeypatch):
    from anas_bot.anas import listing as L

    lc = L.ListingClient(type("Anas", (), {"timeout": 1, "session": None, "_throttle": lambda self: None})())
    monkeypatch.setattr(lc, "prime", lambda: "<html><select name='x'></select></html>")
    found = lc.structures(date(2026, 11, 2))
    assert len(found) == 23 and ("UC", "Autostrada del Mediterraneo") in [(s.code, s.label) for s in found]
    assert {s.code for s in found} == set(L.STRUCTURE_REGIONS)


def test_firewall_block_stops_the_run_and_pauses_the_bot(env):
    """Alla pagina di blocco del firewall: stop immediato, nessuna richiesta per un'ora, poi si riprende."""
    cfg, db, listing, src = env
    p = ListingPoller(db, listing, src, cfg)
    _install(p, listing)
    real = listing.search_page

    def blocked(code, day, page, **kw):
        real(code, day, page, **kw)
        raise BlockedError("firewall ANAS: ricerca * bloccata")
    listing.search_page = blocked
    listing.calls.clear()
    r = p.run(date(2026, 11, 2), now=1000.0)
    assert r.blocked and r.block_started and "bloccata" in r.error
    assert listing.calls == [("BA", 1)]                  # una richiesta sola: niente nuovi tentativi
    r = p.run(date(2026, 11, 2), now=1000.0 + 30 * 60)   # mezz'ora dopo: ancora in pausa
    assert r.blocked and not r.block_started and listing.calls == [("BA", 1)]
    listing.search_page = real
    listing.pages["MI"].insert(0, _closure(212000, "03/11/2026", numero="11/2026/MI"))
    r = p.run(date(2026, 11, 2), now=1000.0 + 61 * 60)   # un'ora dopo: si riprende da soli
    assert not r.blocked and r.new == 1 and [o.ord_id for o in db.pending_ordinanze()] == [212000]


def test_pdf_cap_per_run_defers_the_rest_to_next_run(env):
    """Poche richieste per giro: oltre il tetto dei PDF, le ordinanze che ne hanno bisogno slittano."""
    cfg, db, listing, src = env
    cfg.max_pdf_per_run = 2
    p = ListingPoller(db, listing, src, cfg)
    _install(p, listing)
    for i in range(4):  # 4 chiusure nuove: ognuna vuole il PDF per le province
        listing.pages["BA"].insert(0, _closure(212000 + i, "03/11/2026"))
    r = p.run(date(2026, 11, 2))
    assert r.new == 2 and r.deferred == 2 and len(src.requests) == 2
    r = p.run(date(2026, 11, 2))
    assert r.new == 2 and r.deferred == 0 and len(src.requests) == 4
    assert sorted(o.ord_id for o in db.pending_ordinanze()) == [212000, 212001, 212002, 212003]


def test_many_new_ordinances_are_read_across_runs(env):
    """Se le pagine lette erano ancora tutte nuove, al giro dopo si legge una pagina in più."""
    cfg, db, listing, src = env
    cfg.max_pdf_per_run = 100
    p = ListingPoller(db, listing, src, cfg)
    _install(p, listing)
    for i in range(14):  # 14 novità in un colpo: più delle 2 pagine da 5 lette per giro
        listing.pages["BA"].insert(0, _closure(212000 + i, "03/11/2026"))
    listing.calls.clear()
    found = []
    for _ in range(3):
        r = p.run(date(2026, 11, 2))
        found.append(r.new)
    assert found == [10, 4, 0]
    bari = [page for code, page in listing.calls if code == "BA"]
    assert bari == [1, 2, 1, 2, 3, 4, 1]                 # 2 pagine, poi fino alla 4ª (carry), poi di nuovo 1


def test_search_retries_once_with_fresh_session_after_http_500():
    from anas_bot.anas import listing as L

    class Resp:
        def __init__(self, status, body):
            self.status_code, self._body, self.text, self.headers = status, body, "errore", {}

        def json(self):
            return self._body

    answers = [Resp(500, None), Resp(200, {"tot_pagine": 1, "results": []})]

    class Session:
        def post(self, *a, **k):
            return answers.pop(0)

    from anas_bot.anas.robots import RobotsPolicy
    lc = L.ListingClient(type("Anas", (), {"timeout": 1, "session": Session(), "_throttle": lambda self: None,
                                           "robots": RobotsPolicy.allow_all("t")})())
    primes = []
    lc.prime = lambda: primes.append(1)
    lc._primed = True
    assert lc.search_page("BA", date(2026, 11, 2), 1)["tot_pagine"] == 1
    assert primes == [1]


def test_direction_and_readable_excerpt_from_real_ss36_record():
    """Ordinanza reale 1341/2026/MI, arrivata nel primo giro vero (02/11/2026)."""
    riep = ("<p>L'ordinanza sarà applicata alle seguenti tratte:</p><p><strong>SS 36 DEL LAGO DI COMO E DELLO "
            "SPLUGA</strong> dal km 49+500 al km 51+750 su <strong>tutte le corsie</strong> , Direzione Sondrio "
            "attuando i seguenti provvedimenti: ;<ul><li>chiusura al traffico</li></ul> a partire dal "
            "<strong>02/11/2026</strong> fino al <strong>06/11/2026</strong> nella fascia oraria dalle 21:00 alle "
            "05:00 del giorno successivo Interesserà: tutti gli utenti</p>")
    o = record_to_ordinanza(_rec(1, riep, numero="1341/2026/MI"), "Milano", "u")
    assert o.category == CLOSURE and o.direction == "verso Sondrio"
    assert "Interesser" not in o.excerpt and "attuando" not in o.excerpt and "→" in o.excerpt


def test_block_page_is_recognized_even_when_split_across_lines():
    from anas_bot.anas.client import is_block_page
    page = """<html><head><style>body{margin:0}</style><title>The URL you
      requested has been blocked</title></head><body><h1>Web&nbsp;Page
      Blocked!</h1><p>Attack
      ID: 20000046</p></body></html>"""
    assert is_block_page(page)
    assert not is_block_page("<html><title>Errore interno</title><p>HTTP 500</p></html>")


def test_search_that_refuses_to_list_raises_listing_error(env):
    """Il sito oltre 1.000 risultati risponde esito=false e nessun elenco: errore chiaro, non "zero novità"."""
    cfg, db, listing, src = env
    p = ListingPoller(db, listing, src, cfg)
    listing.search_page = lambda code, day, page, **kw: {"esito": False, "tot_pagine": 0, "tot_record": 3911,
                                                         "results": [], "messaggio": "E' stato ragginto il limite massimo"}
    r = p.run(date(2026, 11, 2))
    assert r.broken and "3911" in r.error and db.get("listing_done_BA") is None


def test_messages_are_flushed_after_each_structure(env):
    """Giro lungo: il job manda i messaggi in coda dopo ogni struttura, non alla fine dell'ora."""
    cfg, db, listing, src = env
    p = ListingPoller(db, listing, src, cfg)
    _install(p, listing)
    calls = []
    p.after_structure = lambda: calls.append(len(listing.calls))
    p.run(date(2026, 11, 2))
    assert len(calls) == 2  # una chiamata per struttura letta (BA, MI)


def test_night_deep_read_finds_new_closure_below_first_page(env):
    """Di notte si leggono 4 pagine per struttura: un'ordinanza nuova a pagina 3 arriva la mattina dopo."""
    cfg, db, listing, src = env
    p = ListingPoller(db, listing, src, cfg)
    _install(p, listing)
    listing.pages["BA"].insert(12, _closure(212500, "03/11/2026"))   # in terza pagina, sotto 12 note
    listing.calls.clear()
    assert p.run(date(2026, 11, 2), hour=14).new == 0              # di giorno: prima pagina, niente di nuovo
    assert [c[1] for c in listing.calls if c[0] == "BA"] == [1]
    listing.calls.clear()
    r = p.run(date(2026, 11, 3), hour=3)                           # di notte: 4 pagine
    assert r.relevant == 1 and [o.ord_id for o in db.pending_ordinanze()] == [212500]
    assert r.silent == r.new - 1                                   # le vecchie sotto lo spartiacque: mute
    assert [c[1] for c in listing.calls if c[0] == "BA"] == [1, 2, 3, 4]
    assert db.get("listing_fast_carry_BA") == "0"                  # la profondità notturna non lascia "carry"


def test_deep_hours_parsing():
    cfg = Config()
    cfg.listing_deep_hours = "0-6"
    assert cfg.is_deep_hour(0) and cfg.is_deep_hour(5) and not cfg.is_deep_hour(6) and not cfg.is_deep_hour(14)
    cfg.listing_deep_hours = "22-6"
    assert cfg.is_deep_hour(23) and cfg.is_deep_hour(2) and not cfg.is_deep_hour(12)
    cfg.listing_deep_hours = ""
    assert not cfg.is_deep_hour(3)


def test_one_structure_in_error_does_not_stop_the_others(env):
    cfg, db, listing, src = env
    p = ListingPoller(db, listing, src, cfg)
    _install(p, listing)
    real = listing.search_page

    def flaky(code, day, page, **kw):
        if code == "BA":
            raise TransientError("elenco BA: connection reset")
        return real(code, day, page, **kw)
    listing.search_page = flaky
    listing.pages["MI"].insert(0, _closure(212000, "03/11/2026", numero="11/2026/MI"))
    r = p.run(date(2026, 11, 2))
    assert r.skipped == ["BA"] and not r.error and not r.blocked
    assert [o.ord_id for o in db.pending_ordinanze()] == [212000]   # Milano arriva lo stesso


def test_two_structures_in_error_in_a_row_pause_like_a_block(env):
    cfg, db, listing, src = env
    p = ListingPoller(db, listing, src, cfg)
    _install(p, listing)
    listing.search_page = lambda code, day, page, **kw: (_ for _ in ()).throw(TransientError("reset"))
    r = p.run(date(2026, 11, 2), now=1000.0)
    assert r.blocked and r.block_started and r.skipped == ["BA", "MI"]   # come un blocco: pausa di un'ora
    assert float(db.get("anas_blocked_until")) == 1000.0 + cfg.block_pause_minutes * 60


def test_closure_of_a_lay_by_is_not_a_road_closure():
    """Ordinanza reale (03/11/2026): chiusura al traffico "su piazzola di sosta" sulla SS 18 VAR: la strada
    resta aperta, per Waze non è una chiusura."""
    rec = _rec(214200, _riep("SS 18 VAR CILENTANA dal km 133+900 al km 134+000, Sapri,", "su piazzola di sosta",
                             ["chiusura al traffico"],
                             "a partire dalle ore 00:00 del <strong>3/11/2026</strong> fino alle ore 24:00 del "
                             "<strong>30/12/2026</strong> esclusi i giorni festivi"))
    o = record_to_ordinanza(rec, "Napoli", "u")
    assert o.category == OTHER


def test_closure_with_unknown_place_phrase_is_sent_but_flagged():
    """"su ponte Bailey provvisorio" non è una dicitura nota: la chiusura parte, con ⚠️ da verificare."""
    from anas_bot.anas.listing import unknown_where
    rec = _rec(777, _riep("SS 16", "su piattaforma galleggiante,", ["chiusura al traffico"],
                          "a partire dal <strong>03/11/2026</strong> fino al <strong>30/11/2026</strong>"))
    o = record_to_ordinanza(rec, "Puglia", "u")
    assert o.category == CLOSURE and o.uncertain and "piattaforma galleggiante" in o.uncertain_why
    assert o.listing_record["ID"] == "777" and "RIEPILOGO" in o.listing_record
    sure = _rec(778, _riep("SS 16", "su <strong>tutte le corsie</strong>,", ["chiusura al traffico"],
                           "a partire dal <strong>03/11/2026</strong>"))
    assert not record_to_ordinanza(sure, "Puglia", "u").uncertain
    assert unknown_where("dal km 10+000 al km 12+000, su tutte le corsie, in direzione nord") == ""


def test_access_closure_names_what_is_closed():
    """RA6, svincolo di Passignano Est (ordinanza reale 718/2026/PG, 03/11/2026): "SVINCOLO CHIUSO", non tutti e tre."""
    from anas_bot.views import title_line
    rec = _rec(900, _riep("RA 6 RACCORDO AUTOSTRADALE BETTOLLE - PERUGIA", "sullo svincolo in entrata, svincolo in uscita, "
                          "Passignano Est direzione Bettolle,", ["chiusura al traffico"],
                          "a partire dal <strong>04/11/2026</strong> fino al <strong>07/11/2026</strong>"), numero="718/2026/PG")
    o = record_to_ordinanza(rec, "Perugia", "u")
    assert o.category == CLOSURE and o.ramp_only and o.access_kind == "svincolo"
    assert title_line(o).startswith("↪️⛔ *SVINCOLO CHIUSO*")


def test_structure_empty_at_install_notifies_its_first_future_ordinance(env):
    """MI è vuota alla presa visione: la sua prima ordinanza, anche con inizio prima dell'installazione, è nuova."""
    cfg, db, listing, src = env
    listing.pages["MI"] = []
    p = ListingPoller(db, listing, src, cfg)
    _install(p, listing)
    assert db.get("listing_done_MI") and db.get("listing_watermark_MI") == "0"
    listing.pages["MI"].insert(0, _closure(212000, "20/10/2026", numero="11/2026/MI"))
    r = p.run(date(2026, 11, 2))
    assert r.relevant == 1 and [o.ord_id for o in db.pending_ordinanze()] == [212000]


def test_hourly_ledger_waits_and_then_gives_up(tmp_path):
    """Il tetto orario vale attraverso i giri: con 3 richieste nell'ultima ora la 4ª aspetta, o rinuncia."""
    from anas_bot.anas.budget import BudgetExhausted, RequestLedger
    db = Database.local(str(tmp_path / "b.sqlite3"))
    clock = {"t": 0.0}
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        clock["t"] += seconds

    led = RequestLedger(db, max_per_hour=3, max_wait=900, now=lambda: clock["t"], sleep=sleep)
    for t in (0, 60, 120):
        clock["t"] = t
        led.before_request()
    clock["t"] = 3000                      # 50 minuti dopo, "giro successivo": la più vecchia esce tra 10 minuti
    led.before_request()
    assert slept and 600 <= slept[0] <= 602 and led.in_last_hour() == 3   # ha aspettato, poi registrato
    clock["t"] = 3605                      # nell'ora: 60, 120, 3601 -> servirebbero 55 s, più del massimo: rinuncia
    strict = RequestLedger(db, max_per_hour=3, max_wait=30, now=lambda: clock["t"], sleep=sleep)
    with pytest.raises(BudgetExhausted):
        strict.before_request()


def test_browser_like_fetches_same_site_assets_only():
    from anas_bot.anas import listing as L

    class Sess:
        def __init__(self):
            self.got = []
        def get(self, url, **kw):
            self.got.append(url)
            return type("R", (), {"status_code": 200, "headers": {}, "text": ""})()
    calls = {"n": 0}
    anas = type("Anas", (), {"timeout": 1, "robots": L.RobotsPolicy.allow_all("x"), "session": Sess(),
                             "_throttle": lambda self: calls.__setitem__("n", calls["n"] + 1)})()
    lc = L.ListingClient(anas)
    page = ('<link rel="stylesheet" href="/css/a.css"><script src="https://www.stradeanas.it/js/b.js"></script>'
            '<script src="https://cdn.altro.it/x.js"></script><link rel="stylesheet" href="//www.stradeanas.it/css/c.css">')
    lc.browser_like = True
    lc._fetch_page_assets(page)
    assert lc.session.got == ["https://www.stradeanas.it/css/a.css", "https://www.stradeanas.it/js/b.js",
                              "https://www.stradeanas.it/css/c.css"]
    assert calls["n"] == 3                               # ogni risorsa passa dal freno (e dal budget orario)


def test_national_search_runs_every_run_before_the_rotation(env):
    """Le urgenze in nazionale: la frana di Milano arriva al giro stesso, anche se MI non è di turno."""
    cfg, db, listing, src = env
    cfg.national_searches = "FEN=Fenomeni naturali/*/Frane e simili"
    cfg.listing_structures_per_run = 1  # per giro solo una struttura a rotazione
    p = ListingPoller(db, listing, src, cfg)
    p.run(date(2026, 11, 1))  # presa visione: NAZ-FEN e BA
    frana = _closure(212000, "03/11/2026", numero="11/2026/MI")
    frana["CAUSA"] = "Fenomeni naturali"
    listing.pages["MI"].insert(0, frana)
    listing.calls.clear()
    r = p.run(date(2026, 11, 2))
    assert listing.calls[0] == (ITALY, 1)                       # prima la nazionale...
    assert [c for c in listing.calls if c[0] != ITALY] == [("MI", 1)]  # ...poi la struttura di turno
    assert r.relevant == 1 and [o.ord_id for o in db.pending_ordinanze()] == [212000]
    assert db.get("listing_fast_rr") == "0"                     # la nazionale non fa avanzare la rotazione


def test_national_search_over_the_cap_is_switched_off_for_the_day(env):
    cfg, db, listing, src = env
    cfg.national_searches = "VIA=Gestione della viabilità"
    real = listing.search_page

    def capped(code, day, page, causa="*", causa_dett="*"):
        if code == ITALY:
            return {"esito": False, "tot_pagine": 0, "tot_record": 2024, "results": [], "messaggio": "limite massimo"}
        return real(code, day, page, causa, causa_dett)
    listing.search_page = capped
    p = ListingPoller(db, listing, src, cfg)
    r = p.run(date(2026, 11, 2))
    assert r.national_off and "2024" in r.national_off[0] and not r.error
    assert db.get("listing_nat_off_NAZ-VIA") == "2026-11-02"
    listing.calls.clear()
    p.run(date(2026, 11, 2))
    assert all(c[0] != ITALY for c in listing.calls)            # per oggi non la riprova


def test_national_searches_config_parsing():
    cfg = Config()
    cfg.national_searches = "FEN=Fenomeni naturali;EMER=*/Ripristino viabilità per emergenze/Emergenze; x=a/b"
    assert cfg.national() == [("FEN", "Fenomeni naturali", "*", "FEN"),
                              ("EMER", "*", "Ripristino viabilità per emergenze", "Emergenze"),
                              ("X", "a", "b", "x")]
