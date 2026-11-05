"""Il bot rispetta il robots.txt di ANAS: non interroga percorsi vietati e si ferma se il sito è in errore."""

from datetime import date

import pytest

from anas_bot.anas.client import TransientError
from anas_bot.anas.listing import PAGE_URL, SEARCH_URL, ListingClient
from anas_bot.anas.robots import RobotsPolicy

UA = "WazeItaliaAnasBot"

# robots.txt reale di stradeanas.it (02/11/2026), ridotto alle righe che contano
REAL_ROBOTS = """
User-agent: *
Allow: /core/*.css$
Disallow: /core/
Disallow: /profiles/
Disallow: /admin/
Disallow: /search/
Disallow: /user/register
Disallow: /user/login
Disallow: /index.php/search/
"""


@pytest.mark.parametrize("path, allowed", [
    ("/it/ordinanze-web", True),
    ("/anas_ordinanzeweb/searchordinanze", True),
    ("/it/anas_ordinanzeweb/getordinanzapdf?ord_id=213628", True),
    ("/search/", False),
    ("/admin/", False),
    ("/user/login", False),
    ("/core/misc/something.js", False),
])
def test_real_robots_allows_ordinances_and_blocks_reserved_paths(path, allowed):
    policy = RobotsPolicy.from_text(REAL_ROBOTS, UA)
    assert policy.allowed("https://www.stradeanas.it" + path) is allowed


def test_real_robots_has_no_crawl_delay():
    assert RobotsPolicy.from_text(REAL_ROBOTS, UA).crawl_delay() == 0.0


def test_allow_all_and_disallow_all():
    assert RobotsPolicy.allow_all(UA).allowed(SEARCH_URL) is True
    assert RobotsPolicy.disallow_all(UA).allowed(SEARCH_URL) is False
    assert RobotsPolicy.disallow_all(UA).allowed(PAGE_URL) is False


class _Resp:
    def __init__(self, status, text=""):
        self.status_code, self.text, self.headers = status, text, {}

    def json(self):
        import json
        return json.loads(self.text)


class _FakeAnas:
    timeout = 1
    user_agent = UA

    def __init__(self, responses):
        self.responses = responses  # url-substring -> _Resp
        self.robots = RobotsPolicy.allow_all(UA)
        self.calls = []

    def _throttle(self, what=""):
        pass

    class session:  # noqa: N801 - basta un .get/.post statici per i test
        pass


def _client(responses):
    anas = _FakeAnas(responses)

    def get(url, timeout=None):
        anas.calls.append(("GET", url))
        for key, resp in responses.items():
            if key in url:
                return resp
        return _Resp(404)

    def post(url, data=None, headers=None, timeout=None):
        anas.calls.append(("POST", url))
        return responses["search"]

    anas.session.get = staticmethod(get)
    anas.session.post = staticmethod(post)
    lc = ListingClient(anas)
    return lc, anas


def test_load_robots_allows_real_site_then_search_proceeds():
    lc, anas = _client({"robots.txt": _Resp(200, REAL_ROBOTS),
                        "search": _Resp(200, '{"tot_pagine":1,"tot_record":0,"results":[]}')})
    lc.load_robots()
    assert anas.robots.allowed(SEARCH_URL) is True
    lc._primed = True
    assert lc.search_page("BA", date(2026, 11, 2), 1)["tot_record"] == 0


def test_blocked_site_5xx_makes_bot_stand_down():
    """Sito in errore (HTTP 500 vero): il bot non deve interrogare nulla in quel giro."""
    lc, anas = _client({"robots.txt": _Resp(500, "Errore interno del server")})
    lc.load_robots()
    assert anas.robots.allowed(SEARCH_URL) is False
    with pytest.raises(TransientError):
        lc.search_page("BA", date(2026, 11, 2), 1)


def test_block_page_on_robots_is_a_firewall_block_whatever_the_status():
    """La pagina di blocco del firewall, con qualunque codice HTTP, è un blocco: pausa, non "sito in errore"."""
    from anas_bot.anas.client import BlockedError
    for status in (403, 500, 503):
        lc, anas = _client({"robots.txt": _Resp(status, "<h1>Web Page Blocked!</h1> Attack ID 20000046")})
        with pytest.raises(BlockedError):
            lc.load_robots()
        assert anas.robots.allowed(SEARCH_URL) is False


def test_robots_disallowing_ordinances_is_respected():
    blocking = "User-agent: *\nDisallow: /anas_ordinanzeweb/\nDisallow: /it/ordinanze-web\n"
    lc, anas = _client({"robots.txt": _Resp(200, blocking)})
    lc.load_robots()
    with pytest.raises(TransientError):
        lc.search_page("BA", date(2026, 11, 2), 1)


def test_session_cookies_survive_between_runs(tmp_path):
    """Il cookie di sessione del sito si conserva nel database: il giro dopo non rilegge la pagina iniziale."""
    from anas_bot.anas.client import AnasClient
    from anas_bot.anas.listing import ListingClient
    from anas_bot.db import Database
    db = Database.local(str(tmp_path / "c.sqlite3"))
    anas = AnasClient("https://www.stradeanas.it/x?ord_id={id}", "t", 0)
    lc = ListingClient(anas)
    assert lc.restore_cookies(db) is False and lc._primed is False      # primo giro: niente da riprendere
    anas.session.cookies.set("cookiesession1", "ABC123", domain="www.stradeanas.it")
    anas.session.cookies.set("altro", "x", domain="example.org")          # di un altro sito: non si salva
    lc.save_cookies(db)
    anas2 = AnasClient("https://www.stradeanas.it/x?ord_id={id}", "t", 0)
    lc2 = ListingClient(anas2)
    assert lc2.restore_cookies(db) is True and lc2._primed is True
    assert {c.name: c.value for c in anas2.session.cookies} == {"cookiesession1": "ABC123"}
