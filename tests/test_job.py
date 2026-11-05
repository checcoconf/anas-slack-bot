"""Il job di GitHub Actions dall'inizio alla fine, e il trasporto verso Cloudflare D1."""

import logging

import pytest

from anas_bot import job
from anas_bot.config import Config
from anas_bot.db import D1Error, D1Http, Database
from tests import samples as s
from tests.fakes import FakeSlack, FakeSource


@pytest.fixture
def cfg():
    c = Config()
    c.slack_bot_token = "xoxb-test"
    c.channel_ids = ["C1"]
    c.admin_channel_id = "CADMIN"
    c.anas_start_id = 100
    c.max_gap = 3
    c.request_delay_seconds = 0
    return c


def test_full_run_then_resume(tmp_path, cfg, caplog):
    path = str(tmp_path / "d1.sqlite3")
    slack = FakeSlack(members={"C1": ["U1", "U2"]})
    db = Database.local(path)

    # primo giro: benvenuti a chi è già nel canale, nessuno ha ancora scelto le zone
    caplog.set_level(logging.INFO)
    job.run(cfg, db, slack, FakeSource({100: s.CLOSURE_SS614}))
    assert {p["channel"] for p in slack.posts} == {"D-U1", "D-U2", "CADMIN"}
    assert "U1" not in caplog.text and "U2" not in caplog.text  # log senza ID utente

    # U1 sceglie l'Abruzzo dal Worker (stesso database)
    db.save_preferences("U1", all_italy=False, regions=["abruzzo"], provinces=[], want_closures=True,
                        want_speed=True)
    slack.posts.clear()

    # giro successivo, in un "nuovo" job: riparte dal cursore e manda solo le novità
    db2 = Database.local(path)
    job.run(cfg, db2, slack, FakeSource({100: s.CLOSURE_SS614, 101: s.MIXED_LANE_AND_CLOSURE}))
    to_u1 = [p for p in slack.posts if p["channel"] == "D-U1"]
    # prima il riepilogo di ciò che era già in vigore nelle zone appena scelte (la SS614), poi la novità
    assert len(to_u1) == 2 and "in vigore" in to_u1[0]["text"] and "SS614" in to_u1[0]["text"]
    assert "SS16" in to_u1[1]["text"] and "SS614" not in to_u1[1]["text"]
    assert db2.cursor() == 101
    assert not [p for p in slack.posts if p["channel"] == "CADMIN"]  # niente avviso al secondo giro


def test_admin_alert_after_repeated_failures(tmp_path, cfg):
    db = Database.local(str(tmp_path / "d.sqlite3"))
    slack = FakeSlack(members={"C1": []})
    src = FakeSource({})
    src.fail_from = 0
    for _ in range(job.ALERT_AFTER_FAILED_RUNS):
        job.run(cfg, db, slack, src)
    alerts = [p for p in slack.posts if p["channel"] == "CADMIN" and "non raggiungibile" in p["text"]]
    assert len(alerts) == 1
    src.fail_from = None
    job.run(cfg, db, slack, src)
    assert "di nuovo raggiungibile" in slack.posts[-1]["text"]


def test_config_requires_database():
    c = Config()
    c.slack_bot_token, c.channel_ids = "xoxb-x", ["C1"]
    assert any("Database mancante" in e for e in c.validate())
    c.local_db_path = "x.sqlite3"
    assert c.validate() == []


class _Resp:
    def __init__(self, data, status=200):
        self._data, self.status_code = data, status

    def json(self):
        return self._data


def test_d1_http_payloads(monkeypatch):
    d1 = D1Http("ACC", "DB", "TOKEN")
    sent = []

    def fake_post(url, json, timeout):
        sent.append((url, json))
        return _Resp({"success": True, "result": [{"results": [{"value": "42"}], "success": True}]})

    monkeypatch.setattr(d1.session, "post", fake_post)
    assert d1.query("SELECT value FROM kv WHERE key=?", ("anas_cursor",)) == [{"value": "42"}]
    d1.batch([("UPDATE users SET paused=? WHERE user_id=?", (True, "U1")), ("DELETE FROM kv", ())])
    url, body = sent[0]
    assert url == "https://api.cloudflare.com/client/v4/accounts/ACC/d1/database/DB/query"
    assert body == {"sql": "SELECT value FROM kv WHERE key=?", "params": ["anas_cursor"]}
    assert sent[1][1] == {"batch": [{"sql": "UPDATE users SET paused=? WHERE user_id=?", "params": [1, "U1"]},
                                    {"sql": "DELETE FROM kv", "params": []}]}
    assert d1.session.headers["Authorization"] == "Bearer TOKEN"


def test_d1_http_error(monkeypatch):
    d1 = D1Http("ACC", "DB", "TOKEN")
    monkeypatch.setattr(d1.session, "post", lambda *a, **k: _Resp(
        {"success": False, "errors": [{"code": 7500, "message": "no such table: kv"}]}, 400))
    with pytest.raises(D1Error, match="no such table"):
        d1.query("SELECT 1")


def test_stall_alert(tmp_path, cfg):
    import time
    db = Database.local(str(tmp_path / "s.sqlite3"))
    slack = FakeSlack(members={"C1": []})
    db.set("anas_cursor", "500")
    db.set("anas_last_found_at", str(time.time() - 80 * 3600))
    job.run(cfg, db, slack, FakeSource({}))
    job.run(cfg, db, slack, FakeSource({}))
    alerts = [p for p in slack.posts if "Nessuna nuova ordinanza" in p["text"]]
    assert len(alerts) == 1  # una volta sola, non a ogni giro


def test_listing_is_primary_and_walk_is_fallback(tmp_path, cfg):
    from tests.test_listing import FakeListing, _closure, _rec, _riep
    from anas_bot.anas.listing import ListingError

    db = Database.local(str(tmp_path / "j.sqlite3"))
    slack = FakeSlack(members={"C1": ["U1"]})
    db.save_preferences("U1", all_italy=True, regions=[], provinces=[], want_closures=True, want_speed=True)
    listing = FakeListing({"BA": [_closure(300, "20/10/2026")], "MI": []})
    src = FakeSource({})
    for _ in range(2):                                   # installazione: prima lettura completa, silenziosa
        job.run(cfg, db, slack, src, listing)
    assert src.requests == []                            # elenco ok: il canale a numeri non parte
    listing.pages["BA"].insert(0, _closure(301, "03/11/2026"))
    listing.pages["MI"].insert(0, _rec(302, _riep("SS 36", "su <strong>tutte le corsie</strong>,",
                                                  ["chiusura a targhe alterne"], "a partire dal 03/11/2026")))
    slack.posts.clear()
    job.run(cfg, db, slack, src, listing)
    dm = [p for p in slack.posts if p["channel"] == "D-U1"]
    assert len(dm) == 1 and "STRADA CHIUSA" in dm[0]["blocks"][3]["text"]["text"]
    alerts = [p["text"] for p in slack.posts if p["channel"] == "CADMIN"]
    assert any("mai visti" in a and "targhe alterne" in a for a in alerts)

    def broken(*a, **k):
        raise ListingError("formato cambiato")
    listing.search_page = broken
    db.set("anas_cursor", "400")
    job.run(cfg, db, slack, src, listing)
    assert src.requests                                  # elenco rotto: parte il canale di riserva
    assert any("non leggibile" in p["text"] for p in slack.posts if p["channel"] == "CADMIN")


def test_schema_statements_can_be_repeated():
    from anas_bot.db import LocalSqlite, schema_statements
    b = LocalSqlite(":memory:")
    stmts = schema_statements()
    assert len(stmts) == 7
    b.batch([(st, ()) for st in stmts])   # seconda volta sulle tabelle già create: nessun errore


def test_app_only_mode_keeps_users_subscribed_without_a_channel(tmp_path, cfg):
    """SLACK_CHANNEL_IDS vuota: nessun riallineamento, chi ha scelto le zone dalla Home resta iscritto."""
    cfg.channel_ids = []
    cfg.local_db_path = str(tmp_path / "a.sqlite3")
    assert not cfg.validate()                                            # il canale non è più obbligatorio
    db = Database.local(cfg.local_db_path)
    db.save_preferences("U1", all_italy=True, regions=[], provinces=[], want_closures=True, want_speed=True)
    slack = FakeSlack(members={})
    from anas_bot.membership import Membership
    assert Membership(db, slack, cfg).reconcile(first_run=True) == (0, 0)
    assert db.get_user("U1").receives


def test_block_at_the_first_page_pauses_the_bot_and_alerts(cfg, monkeypatch):
    """Se già la pagina di prova (o robots.txt) è la pagina di blocco, il giro non deve fare altre richieste."""
    from anas_bot import job as J
    from anas_bot.anas.client import BlockedError
    from anas_bot.listing_poller import BLOCKED_UNTIL
    db = Database.local(":memory:")
    cfg.local_db_path, cfg.admin_slack_bot_token = ":memory:", ""
    slack = FakeSlack(members={})
    J._admin_client = None
    monkeypatch.setattr(J, "open_database", lambda c: db)
    monkeypatch.setattr(J, "build_web_client", lambda token: slack)
    monkeypatch.setattr(J, "choose_route", lambda *a, **k: (_ for _ in ()).throw(BlockedError("firewall ANAS: pagina bloccata")))
    monkeypatch.setattr(J, "run", lambda *a, **k: 0)
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("LOCAL_DB_PATH", ":memory:")
    monkeypatch.setenv("ADMIN_CHANNEL_ID", "CADMIN")
    assert J.main() == 0
    assert float(db.get(BLOCKED_UNTIL)) > 0 and db.get("anas_blocks_total") == "1"
    assert any("🧱" in p["text"] for p in slack.posts)


def test_fallback_schedule_runs_only_if_the_worker_clock_is_silent():
    db = Database.local(":memory:")
    assert job.fallback_run_is_needed(db, "schedule", now=lambda: 10_000.0)        # mai partito: serve
    db.set("last_run_started_at", "9000")                                          # 17 minuti fa
    assert not job.fallback_run_is_needed(db, "schedule", now=lambda: 10_000.0)    # il Worker lavora: no
    assert job.fallback_run_is_needed(db, "workflow_dispatch", now=lambda: 10_000.0)  # avvio manuale/Worker: sempre
    assert job.fallback_run_is_needed(db, "schedule", now=lambda: 9000 + 101 * 60)  # da 101 minuti: serve


def test_pause_ending_during_the_run_is_waited_out(cfg):
    from anas_bot.listing_poller import BLOCKED_UNTIL
    db = Database.local(":memory:")
    slept = []
    clock = {"t": 1000.0}
    sleep = lambda s: slept.append(s) or clock.__setitem__("t", clock["t"] + s)  # noqa: E731
    now = lambda: clock["t"]  # noqa: E731
    assert job.wait_for_pause(db, cfg, now, sleep) and slept == []            # nessuna pausa
    db.set(BLOCKED_UNTIL, str(1000.0 + 5 * 60))                               # finisce tra 5 minuti
    assert job.wait_for_pause(db, cfg, now, sleep) and slept == [301.0]       # aspetta, poi lavora
    db.set(BLOCKED_UNTIL, str(clock["t"] + 45 * 60))                          # ne resterebbero 5: rinuncia
    assert not job.wait_for_pause(db, cfg, now, sleep) and len(slept) == 1


def test_admin_alerts_can_use_a_second_workspace_token(cfg, monkeypatch):
    from anas_bot import job as J
    built = []
    monkeypatch.setattr(J, "build_web_client", lambda token: built.append(token) or FakeSlack(members={}))
    J._admin_client = None
    cfg.admin_channel_id, cfg.admin_slack_bot_token = "CADMIN", "xoxb-altro"
    main_client = FakeSlack(members={})
    J.admin(main_client, cfg, "ciao")
    assert built == ["xoxb-altro"] and not main_client.posts            # non passa dal token principale


def test_end_to_end_day_and_night_with_every_kind_of_subscriber(tmp_path, cfg):
    """Scenario completo su più giri: iscritti con zone e tipi diversi, canale autostrade, riepilogo iniziale,
    giorno (solo prime pagine) e notte (PDF), colonna nuova aggiunta da sola. Nessun doppione, nessun crash."""
    from tests.test_listing import FakeListing, _closure, _rec, _riep
    from anas_bot.db import migrate

    db = Database.local(str(tmp_path / "e2e.sqlite3"))
    assert migrate(db.b) == [] and migrate(db.b) == []                # schema già completo: niente da fare
    cfg.channel_ids, cfg.channel_subscriptions = [], "CAUTO=autostrade"
    slack = FakeSlack(members={})
    listing = FakeListing({"BA": [_closure(300, "20/10/2026")], "MI": [_closure(301, "20/10/2026", numero="5/2026/MI")]})
    src = FakeSource({})
    for _ in range(2):                                                  # installazione: tutto "visto", nessun messaggio
        job.run(cfg, db, slack, src, listing, started=0.0)
    assert [p["channel"] for p in slack.posts] == ["CADMIN"]            # solo "bot attivo": nessun iscritto avvisato
    slack.posts.clear()

    db.save_preferences("U_IT", all_italy=True, regions=[], provinces=[], want_closures=True, want_speed=True)
    db.save_preferences("U_PUG", all_italy=False, regions=["puglia"], provinces=[], want_closures=True,
                        want_speed=False, want_all=True)
    db.save_preferences("U_LOM", all_italy=False, regions=["lombardia"], provinces=[], want_closures=True, want_speed=True)

    # giorno: una chiusura in Puglia, un restringimento in Puglia, una chiusura di rampa sull'A2 (Lombardia finta), una proroga
    listing.pages["BA"].insert(0, _closure(400, "05/11/2026"))
    listing.pages["BA"].insert(0, _rec(401, _riep("SS 100", "su <strong>corsia di marcia</strong>,", ["restringimento carreggiata"],
                                                  "a partire dal <strong>05/11/2026</strong> fino al <strong>20/11/2026</strong>")))
    listing.pages["MI"].insert(0, _rec(402, _riep("A2 AUTOSTRADA DEL MEDITERRANEO", "sulla <strong>rampa di uscita</strong>,",
                                                  ["chiusura al traffico"], "a partire dal <strong>05/11/2026</strong> fino al <strong>09/11/2026</strong>"),
                                       numero="7/2026/MI"))
    listing.pages["BA"].insert(0, _rec(403, "", tipo="Proroga", numero="8/2026/BA"))   # senza riepilogo: serve il PDF
    import anas_bot.job as J
    real_now = J.datetime

    class Day(real_now):
        @classmethod
        def now(cls, tz=None):
            return real_now(2026, 11, 5, 14, 0, tzinfo=tz)
    J.datetime = Day
    try:
        job.run(cfg, db, slack, src, listing, started=0.0)
    finally:
        J.datetime = real_now
    assert src.requests == []                                          # di giorno nessun PDF
    by = lambda ch: [p["text"] for p in slack.posts if p["channel"] == ch]  # noqa: E731
    it, pug, lom, auto = by("D-U_IT"), by("D-U_PUG"), by("D-U_LOM"), by("CAUTO")
    # riepiloghi iniziali (zone appena scelte) prima delle novità
    assert any("in vigore" in t for t in it) and any("in vigore" in t for t in pug) and any("in vigore" in t for t in lom)
    news = [t for t in it if "in vigore" not in t]
    assert any("SS16" in t for t in news) and any("A2" in t for t in news)      # tutta Italia: le due chiusure
    assert any("SS100" in t for t in pug) and not any("SS100" in t for t in it)  # il restringimento solo a chi vuole tutto
    lom_news = [t for t in lom if "in vigore" not in t]
    assert any("A2" in t for t in lom_news) and not any("SS16" in t for t in lom_news)   # Lombardia: solo la sua
    assert auto and all("A2" in t and "SS16" not in t for t in auto)            # canale: solo autostrade
    assert not any("A2" in t for t in pug)                                       # ...e non a chi ha un'altra regione

    # notte: la proroga si legge dal PDF; nessun doppione per nessuno
    n_before = len(slack.posts)
    src.docs[403] = s.EXTENSION_BARI
    cfg.listing_deep_pages = 1

    class Night(real_now):
        @classmethod
        def now(cls, tz=None):
            return real_now(2026, 11, 6, 3, 0, tzinfo=tz)
    J.datetime = Night
    try:
        job.run(cfg, db, slack, src, listing, started=0.0)
        job.run(cfg, db, slack, src, listing, started=0.0)              # un altro giro: niente di nuovo
    finally:
        J.datetime = real_now
    assert src.requests == [403]
    new_posts = slack.posts[n_before:]
    assert any(p["channel"] == "D-U_IT" and "SS172" in p["text"] for p in new_posts)   # la proroga, letta dal PDF
    assert not any(p["channel"] in ("D-U_LOM", "CAUTO") for p in new_posts)            # non è della loro zona
    texts = [(p["channel"], p["text"]) for p in slack.posts]
    assert len(texts) == len(set(texts))                                # nessun messaggio identico ripetuto


def test_migration_never_stops_the_job():
    """Database senza PRAGMA (o con la colonna già presente): la migrazione non solleva mai."""
    from anas_bot.db import migrate

    class NoPragma:
        def __init__(self):
            self.sql = []

        def query(self, sql, params=()):
            self.sql.append(sql)
            if sql.startswith("PRAGMA"):
                raise D1Error("D1 HTTP 400: not authorized")
            if sql.startswith("ALTER"):
                raise D1Error("D1 HTTP 400: duplicate column name")
            return []
    b = NoPragma()
    assert migrate(b) == []                                 # colonna già presente: nessun errore, niente aggiunto
    assert any(s.startswith("ALTER TABLE users ADD COLUMN want_all") for s in b.sql)

    class Fresh(NoPragma):
        def query(self, sql, params=()):
            self.sql.append(sql)
            if sql.startswith("PRAGMA"):
                return [{"name": "user_id"}]
            return []
    assert migrate(Fresh()) == ["users.want_all", "users.all_regions", "users.all_provinces"]  # colonne mancanti: aggiunte
