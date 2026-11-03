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

    def search_page(self, code, day, page):
        self.calls.append((code, page))
        recs = self._italy() if code == ITALY else self.pages[code]
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
    assert (ITALY, 1) in listing.calls                 # trovata dalla lettura veloce della prima pagina


def test_fast_scan_reads_few_pages_when_nothing_is_new(env):
    cfg, db, listing, src = env
    p = ListingPoller(db, listing, src, cfg)
    _install(p, listing)
    listing.calls.clear()
    p.run(date(2026, 11, 2))
    fast = [c for c in listing.calls if c[1] > 0]
    assert fast == [(ITALY, 1)]                         # niente di nuovo: solo la prima pagina


def test_new_closure_deep_in_list_is_found_by_full_rotation(env):
    cfg, db, listing, src = env
    cfg.listing_full_per_run = 1  # rete di sicurezza, spenta di default
    p = ListingPoller(db, listing, src, cfg)
    _install(p, listing)
    listing.pages["BA"].append(_closure(212500, "03/11/2026"))   # in fondo alla lista (pagina 4)
    full_runs = []
    for _ in range(8):  # finita l'installazione, una lettura completa ogni 4 giri
        listing.calls.clear()
        p.run(date(2026, 11, 2))
        full_runs.append(any(c[1] == 0 for c in listing.calls))
    assert full_runs.count(True) == 2
    assert [o.ord_id for o in db.pending_ordinanze()] == [212500]


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

    def blocked(code, day, page):
        real(code, day, page)
        raise BlockedError("firewall ANAS: ricerca * bloccata")
    listing.search_page = blocked
    listing.calls.clear()
    r = p.run(date(2026, 11, 2), now=1000.0)
    assert r.blocked and r.block_started and "bloccata" in r.error
    assert listing.calls == [(ITALY, 1)]                 # una richiesta sola: niente nuovi tentativi
    r = p.run(date(2026, 11, 2), now=1000.0 + 30 * 60)   # mezz'ora dopo: ancora in pausa
    assert r.blocked and not r.block_started and listing.calls == [(ITALY, 1)]
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
    assert found == [9, 5, 0] and sum(found) == 14      # (in pagina 1 c'è anche la vecchia di Milano)
    assert [c[1] for c in listing.calls] == [1, 2, 1, 2, 3, 4, 1]  # 2 pagine, poi fino alla 4ª, poi 1


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
