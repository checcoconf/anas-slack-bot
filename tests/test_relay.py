"""Ponte verso ANAS attraverso il Worker: firma, riscrittura dell'indirizzo, cookie, scelta automatica."""

import requests
from requests.adapters import HTTPAdapter

from anas_bot.anas.client import AnasClient, TransientError
from anas_bot.anas.relay import ANAS_ORIGIN, RelayAdapter, choose_route, relay_signature
from anas_bot.db import Database

URL = "https://www.stradeanas.it/it/anas_ordinanzeweb/getordinanzapdf?ord_id=213628"


def _fake_send(captured):
    def send(self, request, **kwargs):
        captured.append(request)
        r = requests.Response()
        r.status_code = 200
        r._content = b"%PDF-1.7"
        r.url = request.url
        r.request = request
        return r
    return send


def test_signature_matches_worker_format():
    # stesso calcolo di worker/src/relay.js (verificato anche nei test del Worker)
    assert relay_signature("k", "1", "GET", "/x?a=1") == relay_signature("k", "1", "GET", "/x?a=1")
    assert relay_signature("k", "1", "GET", "/x") != relay_signature("k", "1", "POST", "/x")


def test_relay_adapter_rewrites_url_and_signs(monkeypatch):
    captured = []
    monkeypatch.setattr(HTTPAdapter, "send", _fake_send(captured))
    s = requests.Session()
    s.cookies.set("cookiesession1", "abc", domain="www.stradeanas.it")
    s.mount(ANAS_ORIGIN, RelayAdapter("https://bot.example.workers.dev/", "xoxb-k"))
    s.get(URL)
    sent = captured[0]
    assert sent.url == "https://bot.example.workers.dev/anas-relay/it/anas_ordinanzeweb/getordinanzapdf?ord_id=213628"
    target = "/it/anas_ordinanzeweb/getordinanzapdf?ord_id=213628"
    assert sent.headers["X-Relay-Sig"] == relay_signature("xoxb-k", sent.headers["X-Relay-Ts"], "GET", target)
    assert "cookiesession1=abc" in sent.headers["Cookie"]          # i cookie di ANAS viaggiano col ponte


def test_other_sites_are_not_relayed(monkeypatch):
    captured = []
    monkeypatch.setattr(HTTPAdapter, "send", _fake_send(captured))
    s = requests.Session()
    s.mount(ANAS_ORIGIN, RelayAdapter("https://bot.example.workers.dev", "k"))
    s.get("https://slack.com/api/auth.test")
    assert captured[0].url == "https://slack.com/api/auth.test"


def _anas():
    return AnasClient("https://www.stradeanas.it/x?ord_id={id}", "test", 0)


def test_auto_switches_to_worker_when_direct_is_blocked_and_remembers_it():
    db = Database.local(":memory:")
    db.set("worker_url", "https://bot.example.workers.dev")
    anas, attempts = _anas(), []

    def probe():
        attempts.append(anas.via)
        if anas.via == "diretto":
            raise TransientError("connect timeout")

    assert choose_route("auto", db, anas, "k", probe) == "worker"
    assert attempts == ["diretto", "ponte del Worker"]
    assert db.get("anas_route") == "worker"
    # giro successivo: niente più tentativi diretti
    anas2, attempts = _anas(), []
    assert choose_route("auto", db, anas2, "k", probe) == "worker" and attempts == []


def test_auto_stays_direct_when_it_works():
    db = Database.local(":memory:")
    anas = _anas()
    assert choose_route("auto", db, anas, "k", lambda: None) == "diretto"
    assert ANAS_ORIGIN not in anas.session.adapters


def test_blocked_without_known_worker_url_raises():
    db = Database.local(":memory:")

    def probe():
        raise TransientError("connect timeout")
    try:
        choose_route("auto", db, _anas(), "k", probe)
    except TransientError:
        pass
    else:
        raise AssertionError("doveva segnalare l'errore")
