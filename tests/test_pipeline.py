"""Percorso completo: ANAS finto -> database -> coda -> messaggi Slack finti."""

from datetime import date

import pytest

from anas_bot.config import Config
from anas_bot.db import Database
from anas_bot.notifier import Notifier
from anas_bot.poller import Poller
from anas_bot.membership import Membership
from tests import samples as s
from tests.fakes import FakeSlack, FakeSource

TODAY = date(2026, 11, 1)


@pytest.fixture
def cfg():
    c = Config()
    c.channel_ids = ["C1"]
    c.anas_start_id = 100
    c.max_gap = 3
    c.max_requests_per_cycle = 50
    c.request_delay_seconds = 0
    return c


@pytest.fixture
def db(tmp_path):
    return Database.local(str(tmp_path / "bot.sqlite3"))


def _subscribe(db, uid, **kw):
    db.ensure_user(uid)
    base = dict(all_italy=False, regions=[], provinces=[], want_closures=True, want_speed=True)
    base.update(kw)
    db.save_preferences(uid, **base)


def test_poller_walks_gaps_and_stops(db, cfg):
    src = FakeSource({100: s.CLOSURE_SS614, 101: s.LANE_ONLY, 103: s.RAMP_A2})
    r = Poller(db, src, cfg).run_cycle()
    assert r.fetched == 3 and r.relevant == 2 and not r.error
    assert db.cursor() == 103
    assert src.requests == [100, 101, 102, 103, 104, 105, 106]  # 3 buchi di fila dopo il 103 -> stop
    assert db.missing_to_recheck(10, 48) == [102]


def test_restart_resumes_from_cursor_and_finds_late_pdf(db, cfg):
    docs = {100: s.CLOSURE_SS614}
    src = FakeSource(docs)
    Poller(db, src, cfg).run_cycle()
    # "spegnimento": nel frattempo ANAS pubblica 101 e 102
    docs[101] = s.RAMP_A2
    docs[102] = s.SPEED_PERMANENT
    src2 = FakeSource(docs)
    db2 = Database.local(db.b.path)  # nuovo giro del job: riapre lo stesso database
    r = Poller(db2, src2, cfg).run_cycle()
    assert src2.requests[0] == 101  # riparte esattamente dopo il cursore
    assert r.fetched == 2 and db2.cursor() == 102


def test_transient_error_does_not_advance(db, cfg):
    src = FakeSource({100: s.CLOSURE_SS614, 101: s.RAMP_A2})
    src.fail_from = 101
    r = Poller(db, src, cfg).run_cycle()
    assert r.error and db.cursor() == 100
    src.fail_from = None
    Poller(db, src, cfg).run_cycle()
    assert db.cursor() == 101


def test_end_to_end_notifications(db, cfg):
    slack = FakeSlack()
    _subscribe(db, "U_ABRUZZO", regions=["abruzzo"])
    _subscribe(db, "U_COSENZA", provinces=["CS"])
    _subscribe(db, "U_ALL", all_italy=True, want_speed=False)
    _subscribe(db, "U_SPEED", provinces=["FG"], want_closures=False)
    _subscribe(db, "U_CAGLIARI", provinces=["CA"])  # riceve la SS131 senza provincia (fallback regione)
    db.ensure_user("U_NOPREFS")  # entrato ma non ha ancora scelto: niente

    src = FakeSource({100: s.CLOSURE_SS614, 101: s.RAMP_A2, 102: s.SPEED_PERMANENT, 103: s.LANE_ONLY,
                      104: s.NO_PROVINCE, 105: s.EXPIRED})
    Poller(db, src, cfg).run_cycle()
    res = Notifier(db, slack).run(TODAY)

    def got(uid):
        ids = []
        for p in slack.posts_to(uid):
            ids += [b for b in p["blocks"] if b["type"] == "context"
                    and b["elements"][0]["text"].startswith("🏛️")]
        return len(ids)

    assert got("U_ABRUZZO") == 1          # SS614 (la scaduta e le corsie no)
    assert got("U_COSENZA") == 1          # rampa A2
    assert got("U_ALL") == 3              # 614, A2, SS131; niente limite (ha escluso i limiti)
    assert got("U_SPEED") == 1            # solo il limite a Foggia
    assert got("U_CAGLIARI") == 1         # SS131, provincia non determinata
    assert slack.posts_to("U_NOPREFS") == []
    assert res.skipped_expired == 1
    # un solo messaggio per utente, anche con più ordinanze
    assert len(slack.posts_to("U_ALL")) == 1

    # Secondo giro: nessun doppione
    slack.posts.clear()
    Notifier(db, slack).run(TODAY)
    assert slack.posts == []


def test_slack_failure_keeps_queue(db, cfg):
    slack = FakeSlack()
    _subscribe(db, "U1", all_italy=True)
    slack.fail_users["U1"] = "ratelimited"
    Poller(db, FakeSource({100: s.CLOSURE_SS614}), cfg).run_cycle()
    Notifier(db, slack).run(TODAY)
    assert slack.posts == [] and db.pending_deliveries() == {"U1": [100]}
    del slack.fail_users["U1"]
    Notifier(db, slack).run(TODAY)
    assert len(slack.posts_to("U1")) == 1 and db.pending_deliveries() == {}


def test_paused_or_left_user_gets_nothing(db, cfg):
    slack = FakeSlack()
    _subscribe(db, "U1", all_italy=True)
    _subscribe(db, "U2", all_italy=True)
    db.set_paused("U1", True)
    db.set_in_channel("U2", False)
    Poller(db, FakeSource({100: s.CLOSURE_SS614}), cfg).run_cycle()
    Notifier(db, slack).run(TODAY)
    assert slack.posts == []


def test_reconcile_welcomes_and_marks_leavers(db, cfg):
    slack = FakeSlack(members={"C1": ["U1", "U2", "BOT"]}, bots={"BOT"})
    m = Membership(db, slack, cfg)
    welcomed, left = m.reconcile(first_run=True)
    assert welcomed == 2 and left == 0
    assert {p["channel"] for p in slack.posts} == {"D-U1", "D-U2"}
    # U2 esce mentre il bot è spento; U3 entra
    slack.members["C1"] = ["U1", "U3"]
    slack.posts.clear()
    welcomed, left = m.reconcile()
    assert welcomed == 1 and left == 1
    assert db.get_user("U2").in_channel is False
    assert [p["channel"] for p in slack.posts] == ["D-U3"]  # U1 non riceve un secondo benvenuto


def test_existing_members_can_be_skipped(db, cfg):
    cfg.welcome_existing_members = False
    slack = FakeSlack(members={"C1": ["U1"]})
    Membership(db, slack, cfg).reconcile(first_run=True)
    assert slack.posts == []


def test_long_gap_is_crossed_by_lookahead(db, cfg):
    """La numerazione salta 60 numeri: il passo-passo si ferma, l'assaggio più avanti lo supera
    e i numeri del buco vengono ricontrollati: alla fine non manca nessuna ordinanza."""
    cfg.lookahead_after_hours = 0
    docs = {100: s.CLOSURE_SS614, **{i: s.LANE_ONLY for i in range(160, 261)}}
    src = FakeSource(docs)
    r = Poller(db, src, cfg).run_cycle()
    assert db.cursor() == 200 and r.more_pending       # 150 vuoto, 200 esiste
    assert 160 in db.missing_to_recheck(500, 168)        # il buco va in ricontrollo
    for _ in range(10):
        Poller(db, src, cfg).run_cycle()
    assert db.known_ids(100, 300) == set(docs)          # recuperate tutte, nessuna persa


def test_no_lookahead_while_ordinances_keep_coming(db, cfg):
    src = FakeSource({100: s.CLOSURE_SS614})
    Poller(db, src, cfg).run_cycle()                   # appena trovata una: niente assaggi
    assert max(src.requests) == 103
