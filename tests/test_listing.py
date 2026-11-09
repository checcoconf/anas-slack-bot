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
    assert len(KNOWN_MEASURES) == 79  # 77 dal collaudo del 02/11 + le voci viste dopo (una per riga, con la data)
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

def _useful(db):
    """Le ordinanze in coda utili per Waze (chiusure, aperture, limiti): le altre ci passano pure, per chi
    ha scelto di ricevere tutto, ma qui non interessano."""
    from anas_bot.db import RELEVANT
    return [o for o in db.pending_ordinanze() if o.category in RELEVANT]


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
        return [Structure(c, {"BA": "Puglia", "MI": "Lombardia", "FI": "Toscana"}[c]) for c in self.pages]

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
    cfg.max_pdf_per_run_day = 0  # i test sulla provincia diurna lo accendono da soli
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
    assert _useful(db) == []                 # 13 chiusure vecchie: nessuna in coda
    assert src.requests == []                           # e nessun PDF scaricato per le vecchie


def test_new_closure_at_top_of_list_is_notified_next_run(env):
    cfg, db, listing, src = env
    p = ListingPoller(db, listing, src, cfg)
    _install(p, listing)
    listing.pages["MI"].insert(0, _closure(212000, "03/11/2026", numero="11/2026/MI"))  # numero BASSO
    r = p.run(date(2026, 11, 2))
    assert r.new == 1 and r.relevant == 1
    assert [o.ord_id for o in _useful(db)] == [212000]
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
    assert [o.ord_id for o in _useful(db)] == [400]


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
    p.run(date(2026, 11, 2), hour=3)   # di notte: i PDF si leggono
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
    cfg.listing_deep_pages = 1
    r = p.run(date(2026, 11, 2), hour=3)   # di notte: i PDF si leggono
    o = db.get_ordinanza(213628)
    assert r.new == 1 and r.relevant == 0 and _useful(db) == []
    assert o.category == OTHER and o.extension and o.end_date == "2026-11-30" and o.number == "621/2026/UC"


def test_listing_upgrades_ordinance_misclassified_by_number_channel(env):
    cfg, db, listing, src = env
    p = ListingPoller(db, listing, src, cfg)
    _install(p, listing)
    from anas_bot.anas.parser import parse_ordinanza
    db.save_ordinanza(parse_ordinanza(555, s.LANE_ONLY), "")    # canale a numeri: "altro"
    listing.pages["BA"].insert(0, _closure(555, "03/11/2026"))
    r = p.run(date(2026, 11, 2))
    assert r.upgraded == 1 and [o.ord_id for o in _useful(db)] == [555]


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
    assert not r.blocked and r.new == 1 and [o.ord_id for o in _useful(db)] == [212000]


def test_pdf_cap_per_run_defers_the_rest_to_next_run(env):
    """Poche richieste per giro: oltre il tetto dei PDF, le ordinanze che ne hanno bisogno slittano."""
    cfg, db, listing, src = env
    cfg.max_pdf_per_run = 2
    p = ListingPoller(db, listing, src, cfg)
    _install(p, listing)
    for i in range(4):  # 4 chiusure nuove: di notte ognuna vuole il PDF per le province
        listing.pages["BA"].insert(0, _closure(212000 + i, "03/11/2026"))
    cfg.listing_deep_pages = 1
    r = p.run(date(2026, 11, 2), hour=3)
    assert r.new == 2 and r.deferred == 2 and len(src.requests) == 2
    r = p.run(date(2026, 11, 2), hour=3)
    assert r.new == 2 and r.deferred == 0 and len(src.requests) == 4
    assert sorted(o.ord_id for o in _useful(db)) == [212000, 212001, 212002, 212003]


def test_by_day_closures_go_out_without_pdf_and_extensions_wait_for_the_night(env):
    """Di giorno il budget va alle prime pagine: una chiusura nuova parte subito senza PDF (regione della
    struttura, provincia non determinata); una proroga, che senza PDF non si capisce, aspetta la notte."""
    cfg, db, listing, src = env
    cfg.max_pdf_per_run_day = 1
    p = ListingPoller(db, listing, src, cfg)
    _install(p, listing)
    cfg.listing_deep_pages = 1
    listing.pages["BA"].insert(0, _closure(213700, "03/11/2026"))
    listing.pages["BA"].insert(0, {**BARI["results"][0], "ID": "213701", "NUMERO_ORDINANZA": "900/2026/BA"})  # proroga
    r = p.run(date(2026, 11, 2), hour=14)
    assert r.new == 1 and r.relevant == 1 and r.deferred == 1 and src.requests == [213700]   # 1 PDF di giorno: la provincia della chiusura
    assert [o.ord_id for o in _useful(db)] == [213700]
    src.docs[213701] = s.EXTENSION_BARI
    r = p.run(date(2026, 11, 3), hour=3)                      # notte: la proroga si legge dal PDF
    assert r.deferred == 0 and src.requests == [213700, 213701]


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
    lc = L.ListingClient(type("Anas", (), {"timeout": 1, "session": Session(), "_throttle": lambda self, what="": None,
                                           "robots": RobotsPolicy.allow_all("t")})())
    primes = []
    lc.prime = lambda: primes.append(1)
    lc._primed = True
    assert lc.search_page("BA", date(2026, 11, 2), 1)["tot_pagine"] == 1
    assert primes == [1]


def test_block_page_on_search_is_recognized_whatever_the_status():
    """FortiWeb può mandare la pagina di blocco con 403 o 503: non è un "formato cambiato" né un errore di rete."""
    from anas_bot.anas import listing as L
    from anas_bot.anas.robots import RobotsPolicy

    class Resp:
        def __init__(self, status, text):
            self.status_code, self.text, self.headers = status, text, {}

        def json(self):
            raise ValueError("non JSON")

    for status in (403, 500, 503):
        class Session:
            def post(self, *a, **k):
                return Resp(status, "<html><h1>Web Page Blocked!</h1><p>Attack ID 20000046</p></html>")
        lc = L.ListingClient(type("Anas", (), {"timeout": 1, "session": Session(), "_throttle": lambda self, what="": None,
                                               "robots": RobotsPolicy.allow_all("t")})())
        lc._primed = True
        with pytest.raises(BlockedError):
            lc.search_page("BA", date(2026, 11, 2), 1)


def test_prime_is_remembered_only_when_the_page_was_really_read():
    from anas_bot.anas import listing as L
    from anas_bot.anas.robots import RobotsPolicy

    class Resp:
        def __init__(self, status):
            self.status_code, self.text, self.headers = status, "errore", {}

    class Session:
        def get(self, *a, **k):
            return Resp(502)
    lc = L.ListingClient(type("Anas", (), {"timeout": 1, "session": Session(), "_throttle": lambda self, what="": None,
                                           "robots": RobotsPolicy.allow_all("t")})())
    with pytest.raises(TransientError):
        lc.prime()
    assert lc._primed is False   # la prossima ricerca riapre la pagina (serve il cookie di sessione)


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
    assert r.relevant == 1 and [o.ord_id for o in _useful(db)] == [212500]
    assert r.silent == r.new - 1                                   # le vecchie sotto lo spartiacque: mute
    assert [c[1] for c in listing.calls if c[0] == "BA"] == [1, 2, 3, 4]
    assert db.get("listing_fast_carry_BA") == "0"                  # la profondità notturna non lascia "carry"


def test_deadline_stops_the_structure_after_the_first_page(env, monkeypatch):
    """Tempo del giro finito a metà struttura: la prima pagina si legge sempre, le altre al giro dopo.
    (Senza questo freno una lettura profonda iniziata al limite sforava il timeout di GitHub.)"""
    from anas_bot import listing_poller as LP
    cfg, db, listing, src = env
    p = ListingPoller(db, listing, src, cfg)
    _install(p, listing)
    clock = {"t": 0.0}
    monkeypatch.setattr(LP.time, "monotonic", lambda: clock["t"])
    real = listing.search_page

    def slow(code, day, page, **kw):
        clock["t"] += 400.0                       # ogni richiesta "costa" 400 s
        return real(code, day, page, **kw)
    listing.search_page = slow
    listing.calls.clear()
    r = p.run(date(2026, 11, 3), hour=3, deadline=300.0)   # di notte (4 pagine), ma il tempo finisce dopo la prima
    assert [c[1] for c in listing.calls if c[0] == "BA"] == [1] and not r.error
    assert r.structures == ["BA"]                           # le altre strutture al giro dopo


def test_deep_hours_parsing():
    cfg = Config()
    cfg.listing_deep_hours = "0-6"
    assert cfg.is_deep_hour(0) and cfg.is_deep_hour(5) and not cfg.is_deep_hour(6) and not cfg.is_deep_hour(14)
    cfg.listing_deep_hours = "22-6"
    assert cfg.is_deep_hour(23) and cfg.is_deep_hour(2) and not cfg.is_deep_hour(12)
    cfg.listing_deep_hours = ""
    assert not cfg.is_deep_hour(3)


def test_deep_hours_default_when_github_passes_an_empty_variable(monkeypatch):
    """GitHub passa LISTING_DEEP_HOURS="" se la variabile non esiste: deve valere il default 0-6, non "mai"
    (dal rilascio la lettura notturna e i PDF di notte erano spenti per questo, 07/11/2026)."""
    monkeypatch.setenv("LISTING_DEEP_HOURS", "")
    cfg = Config.from_env()
    assert cfg.listing_deep_hours == "0-6" and cfg.is_deep_hour(1)
    monkeypatch.setenv("LISTING_DEEP_HOURS", "no")
    assert not Config.from_env().is_deep_hour(1)
    monkeypatch.setenv("LISTING_DEEP_HOURS", "0-8")
    assert Config.from_env().is_deep_hour(7)


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
    assert [o.ord_id for o in _useful(db)] == [212000]   # Milano arriva lo stesso


def test_three_structures_in_error_in_a_row_end_the_run_without_pause(env):
    cfg, db, listing, src = env
    listing.pages["FI"] = []
    p = ListingPoller(db, listing, src, cfg)
    _install(p, listing)
    listing.search_page = lambda code, day, page, **kw: (_ for _ in ()).throw(TransientError("reset"))
    r = p.run(date(2026, 11, 2), now=1000.0)
    assert r.error and not r.blocked and r.skipped == ["BA", "MI", "FI"]   # rete giù: si riprova all'ora dopo
    assert db.get("anas_blocked_until") is None                              # ...senza la pausa da blocco


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
    assert r.relevant == 1 and [o.ord_id for o in _useful(db)] == [212000]


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




def test_other_ordinance_without_province_waits_for_the_night_pdf_when_someone_follows_a_province(env):
    """Chi segue le "altre ordinanze" per provincia (Taranto) non deve ricevere tutta la Puglia: di giorno
    l'ordinanza senza provincia resta in sospeso, di notte si legge il PDF e si consegna solo se è di Taranto."""
    cfg, db, listing, src = env
    p = ListingPoller(db, listing, src, cfg)
    _install(p, listing)
    db.ensure_user("U_TA")
    db.save_preferences("U_TA", all_italy=True, regions=[], provinces=[], want_closures=True, want_speed=True,
                        want_all=True, all_provinces=["TA"])
    cfg.listing_deep_pages = 1
    works = _rec(213800, _riep("SS 7 APPIA", "su <strong>corsia di marcia</strong>,", ["restringimento carreggiata"],
                               "a partire dal <strong>03/11/2026</strong> fino al <strong>30/11/2026</strong>"))
    listing.pages["BA"].insert(0, works)
    r = p.run(date(2026, 11, 3), hour=14)
    assert r.new == 0 and r.deferred == 1 and src.requests == []          # giorno: in sospeso, nessun PDF
    src.docs[213800] = "ALLA PREFETTURA DI TARANTO\nAL COMUNE DI GROTTAGLIE\nORDINANZA N. 900/2026/BA\nrestringimento carreggiata SS 7"
    r = p.run(date(2026, 11, 4), hour=3)
    assert r.new == 1 and r.deferred == 0 and src.requests == [213800]    # notte: PDF letto
    o = db.get_ordinanza(213800)
    assert o.provinces == ["TA"] and o.category == "altro"
    # senza iscritti per provincia nelle "altre", niente PDF: si salva subito (la regione basta)
    db.save_preferences("U_TA", all_italy=True, regions=[], provinces=[], want_closures=True, want_speed=True,
                        want_all=True, all_regions=["puglia"])
    listing.pages["BA"].insert(0, _rec(213801, works["RIEPILOGO"]))
    r = p.run(date(2026, 11, 4), hour=14)
    assert r.new == 1 and r.deferred == 0 and src.requests == [213800]


def test_type_b_reclassification_is_a_permanent_limit_not_a_closure():
    """Ordinanza reale 05/11/2026 (SS 719 Prato-Pistoia): "divieto di transito, limite 70 km/h ... interesserà
    tutti gli utenti, veicoli a trazione animale, velocipedi, veicoli a braccia, ...". Il divieto è per le
    categorie elencate (strada tipo B), le auto passano: non è una chiusura; il 70 è un limite nuovo, definitivo."""
    from anas_bot.anas.listing import everyone
    from anas_bot.anas.parser import SPEED
    riep = ("L'Ordinanza sar&agrave; applicata alla tratta <strong>SS 719 PRATO - PISTOIA (DECLASSATA DI PRATO)</strong> "
            "dal km 4+215 al km 7+482, classificazione Strada Statale Tipo B, attuando i seguenti provvedimenti:<br> "
            "<ul><li>divieto di transito</li><li>limite di velocita 70Km/h</li></ul> a partire dal <strong>09/11/2026</strong>"
            "<br> Interesser&agrave;: tutti gli utenti, veicoli a trazione animale , velocipedi , veicoli a braccia , "
            "macchine agricole , ciclomotori , motocarrozzette , ciclomotori e motocicli<br><br>")
    o = record_to_ordinanza(_rec(777, riep, causa_dett="Classificazione strada", numero="500/2026/FI"), "Toscana", "u")
    assert o.category == SPEED and o.speeds == [70] and o.open_ended and o.roads == ["SS719"]
    assert everyone("tutti gli utenti") and everyone("tutti gli utenti, tranne mezzi di soccorso")
    assert everyone("tutti gli utenti ; autocarri")                      # due gruppi: uno vale per tutti
    assert not everyone("tutti gli utenti, velocipedi, veicoli a braccia")
    assert not everyone("tutti gli utenti, veicoli aventi massa superiore a 3,5 t")


def test_one_carriageway_closed_with_contraflow_on_the_other_is_a_directional_closure():
    """Carreggiate separate: Nord chiusa (o deviata sull'opposta), Sud in doppio senso. Per Waze si chiude la Nord."""
    for measure in ("chiusura al traffico", "deviazione del traffico su carreggiata opposta"):
        riep = ("L'Ordinanza sar&agrave; applicata alle seguenti tratte:<br><strong>SS 16 ADRIATICA</strong> dal km 800+000 "
                "al km 805+000 sulla <strong>carreggiata Nord</strong>, Direzione Bari attuando i seguenti provvedimenti: ;"
                f"<ul><li>{measure}</li></ul> a partire dal <strong>06/11/2026</strong> fino al <strong>20/11/2026</strong> "
                "Interesser&agrave;: tutti gli utenti<br><strong>SS 16 ADRIATICA</strong> dal km 800+000 al km 805+000 sulla "
                "<strong>carreggiata Sud</strong>, Direzione Lecce attuando i seguenti provvedimenti: ;<ul><li>doppio senso di "
                "circolazione</li><li>limite di velocita 50Km/h</li></ul> a partire dal <strong>06/11/2026</strong> fino al "
                "<strong>20/11/2026</strong> Interesser&agrave;: tutti gli utenti<br>")
        o = record_to_ordinanza(_rec(990, riep), "Puglia", "u")
        assert o.category == CLOSURE and o.direction == "verso Bari" and not o.uncertain, measure


def test_atlas_learns_province_from_pdf_and_reuses_it_without_pdf(env):
    """La prima chiusura sulla SS 16 km 800-805 legge il PDF (1 al giorno per giro) e impara "Bari";
    la seconda sullo stesso tratto ha la provincia senza PDF. Un tratto diverso non eredita niente."""
    from anas_bot.atlante import Atlante, km_to_m
    assert km_to_m("12+500") == 12500 and km_to_m("7") == 7000 and km_to_m("") is None
    cfg, db, listing, src = env
    cfg.max_pdf_per_run_day = 1
    p = ListingPoller(db, listing, src, cfg)
    _install(p, listing)
    src.docs[214000] = "ALLA PREFETTURA DI BARI\nAL COMUNE DI MOLA DI BARI\nORDINANZA N. 1/2026/BA\nchiusura"
    listing.pages["BA"].insert(0, _closure(214000, "03/11/2026"))               # SS 16, km dal riepilogo
    r = p.run(date(2026, 11, 3), hour=14)
    o = db.get_ordinanza(214000)
    assert r.relevant == 1 and src.requests == [214000] and o.provinces == ["BA"]
    atl = Atlante(db.b)
    assert atl.lookup(["SS16"], o.km_from, o.km_to) == ["BA"]                 # imparato
    assert atl.lookup(["SS16"], "500+000", "501+000") == []                    # altro tratto: non sa
    assert atl.lookup(["SS99"], "", "") == []
    listing.pages["BA"].insert(0, _closure(214001, "04/11/2026"))               # stesso tratto, il giorno dopo
    r = p.run(date(2026, 11, 4), hour=14)
    o2 = db.get_ordinanza(214001)
    assert o2.provinces == ["BA"] and o2.province_inferred and src.requests == [214000]   # nessun PDF in più


def test_daytime_pdf_is_at_most_one_per_run(env):
    cfg, db, listing, src = env
    cfg.max_pdf_per_run_day = 1
    p = ListingPoller(db, listing, src, cfg)
    _install(p, listing)
    for i in range(3):
        listing.pages["BA"].insert(0, _rec(214100 + i, _riep(f"SS {700 + i}", "su <strong>tutte le corsie</strong>,", ["chiusura al traffico"],
                                                            "a partire dal <strong>03/11/2026</strong>")))
    for i in range(3):
        src.docs[214100 + i] = "ALLA PREFETTURA DI TARANTO\nORDINANZA\nchiusura"
    r = p.run(date(2026, 11, 3), hour=14)
    assert r.relevant == 1 and r.deferred == 2 and len(src.requests) == 1       # tre chiusure, un PDF: le altre aspettano un giro
    r = p.run(date(2026, 11, 3), hour=15)
    assert r.relevant == 2 and r.deferred == 0 and len(src.requests) == 2       # un altro PDF; la terza parte con la regione
    assert sum(1 for i in range(3) if db.get_ordinanza(214100 + i).provinces == ["TA"]) == 2


def test_atlas_is_seeded_once_from_the_archive(env):
    """Le ordinanze già in archivio con provincia (lette dal PDF) riempiono l'atlante al primo giro, senza richieste."""
    from anas_bot.anas.parser import Ordinanza
    from anas_bot.atlante import Atlante
    cfg, db, listing, src = env
    o = Ordinanza(ord_id=5000, category="chiusura", roads=["SS268"], km_from="0+000", km_to="0+725",
                  provinces=["NA"], regions=["campania"], pdf_url="u")
    db.save_ordinanza(o, "", silent=True)
    p = ListingPoller(db, listing, src, cfg)
    _install(p, listing)
    assert Atlante(db.b).lookup(["SS268"], "0+100", "0+500") == ["NA"]
    assert db.get("atlante_seeded") == "1" and src.requests == []


def test_worker_401_is_relay_rejected():
    from anas_bot.anas import listing as L
    from anas_bot.anas.robots import RobotsPolicy

    class Resp:
        status_code, text, headers = 401, "Firma non valida", {}

        def json(self):
            raise ValueError("non JSON")

    class Session:
        def post(self, *a, **k):
            return Resp()
    lc = L.ListingClient(type("Anas", (), {"timeout": 1, "session": Session(), "_throttle": lambda self, what="": None,
                                           "robots": RobotsPolicy.allow_all("t")})())
    lc._primed = True
    with pytest.raises(L.RelayRejected):
        lc.search_page("BA", date(2026, 11, 2), 1)


def test_lane_narrowing_with_closure_on_a_ramp_is_not_a_closure():
    """749/2026/BA (SS 7, svincolo in uscita verso la A14, 10/11/2026): "restringimento carreggiata destra" +
    "chiusura al traffico" = chiusura di una corsia (tavole del PDF: corsia di emergenza e corsia di marcia),
    il traffico passa. Va tra le "altre ordinanze", non tra le chiusure, e senza "carreggiata Destra" come direzione."""
    rec = _rec(215301, _riep("SS 7 VIA APPIA dal km 631+700 al km 631+000",
                             "sullo <strong>svincolo in uscita</strong>, compreso il ramo di allacciamento con la "
                             "Autostrada A14",
                             ["restringimento carreggiata destra", "chiusura al traffico"],
                             "a partire dal <strong>11/11/2026</strong> fino al <strong>12/11/2026</strong> nella "
                             "fascia oraria dalle 22:00 alle 06:00 del giorno successivo"),
               numero="749/2026/BA")
    o = record_to_ordinanza(rec, "Bari", "u")
    assert o.category == OTHER
    assert o.direction == ""


def test_ramp_closure_without_narrowing_is_still_a_closure():
    rec = _rec(215302, _riep("SS 7 VIA APPIA dal km 631+700 al km 631+000", "sullo <strong>svincolo in uscita</strong>",
                             ["chiusura al traffico"], "a partire dal <strong>11/11/2026</strong>"))
    o = record_to_ordinanza(rec, "Bari", "u")
    assert o.category == CLOSURE and o.ramp_only


def test_all_lanes_closed_with_narrowing_stays_a_closure():
    """SS 100, fase 2 (cantiere notturno con chiusura totale della carreggiata in dir. Bari): "tutte le corsie" +
    "restringimento carreggiata sinistra" + "chiusura al traffico" resta una chiusura: il restringimento è di
    un'altra fase, la carreggiata è chiusa."""
    rec = _rec(215303, _riep("SS 100 DI GIOIA DEL COLLE dal km 17+000 al km 18+600", "su <strong>tutte le corsie</strong>,",
                             ["restringimento carreggiata sinistra", "chiusura al traffico"],
                             "a partire dal <strong>11/11/2026</strong>"))
    assert record_to_ordinanza(rec, "Bari", "u").category == CLOSURE


def test_waiting_items_do_not_make_the_bot_read_extra_pages(env):
    """Una proroga che aspetta il PDF della notte: al primo passaggio è una novità (il bot guarda anche la
    pagina 2), dal secondo no (si ferma alla pagina 1), così il giro d'Italia non si allunga (09/11/2026:
    giro passato da ~2,5 a ~4,5 ore per le attese). Di notte il PDF si legge e l'attesa sparisce."""
    cfg, db, listing, src = env
    p = ListingPoller(db, listing, src, cfg)
    _install(p, listing)
    src.docs[213700] = "ORDINANZA N°950/2026/BA\\nORDINA la proroga dell'ordinanza n. 900/2026/BA fino al 15/12/2026"
    proroga = {"ID": "213700", "TIPO_ORDINANZA": "Proroga", "NUMERO_ORDINANZA": "950/2026/BA", "COMPARTIMENTO": "Bari",
               "CAUSA": "Cantiere", "CAUSA_DETT": "", "RIEPILOGO": "", "PROROGA_DATA": "15/12/2026"}
    listing.pages["BA"].insert(0, proroga)

    def ba_pages():
        return [pg for code, pg in listing.calls if code == "BA"]

    listing.calls.clear()
    r = ListingPoller(db, listing, src, cfg).run(date(2026, 11, 2), hour=14)  # di giorno: niente PDF di proroghe
    assert r.deferred == 1 and ba_pages() == [1, 2]
    assert "213700" in json.loads(db.get("listing_waiting"))

    listing.calls.clear()
    r = ListingPoller(db, listing, src, cfg).run(date(2026, 11, 2), hour=16)
    assert r.deferred == 1 and ba_pages() == [1]  # già in attesa: niente pagina 2

    ListingPoller(db, listing, src, cfg).run(date(2026, 11, 3), hour=3)  # di notte: PDF letto, proroga salvata
    assert db.get_ordinanza(213700) is not None
    assert "213700" not in json.loads(db.get("listing_waiting") or "{}")
