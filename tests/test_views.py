"""Messaggi Slack: limiti di Block Kit, emoji, file condiviso con il Worker."""

from anas_bot import views
from anas_bot.anas.parser import parse_ordinanza
from anas_bot import export_worker
from tests import samples as s


def test_dropdown_limits():
    groups = views.province_option_groups()
    assert len(groups) == 20 and sum(len(g["options"]) for g in groups) == 110
    assert all(len(g["options"]) <= 100 for g in groups)
    assert all(len(o["text"]["text"]) <= 75 for g in groups for o in g["options"])
    assert len(views.region_options()) == 20
    sard = next(g for g in groups if g["label"]["text"] == "Sardegna")
    assert "OT" in [o["value"] for o in sard["options"]]


def test_notification_blocks_limits():
    ords = [parse_ordinanza(i, s.CLOSURE_SS614, "https://x") for i in range(40)]
    msgs = views.notification_messages(ords)
    assert len(msgs) == 3
    assert all(len(m["blocks"]) <= 50 for m, _ in msgs)
    assert sum(len(ids) for _, ids in msgs) == 40


def test_notification_is_readable_with_emoji():
    o = parse_ordinanza(2, s.RAMP_A2, "https://anas.test/2.pdf")
    (msg, ids), = views.notification_messages([o])
    text = msg["blocks"][3]["text"]["text"]
    assert text.startswith("↪️⛔ *RAMPA / SVINCOLO CHIUSO*")
    for piece in ("🛣️ *A2*", "📏 km 187+748", "➡️ carreggiata Nord", "📍 Cosenza (CS)",
                  "📅 dal 12/11/2026 al 15/11/2026", "🌙 solo di notte, 22:00–07:00"):
        assert piece in text
    assert msg["blocks"][3]["accessory"]["url"] == "https://anas.test/2.pdf"
    assert msg["blocks"][1]["elements"][0]["text"] == "⛔ chiusura ×1"


def test_worker_json_is_up_to_date():
    """Se fallisce: lancia `python -m anas_bot.export_worker` e committa il file."""
    assert export_worker.OUT.read_text(encoding="utf-8") == export_worker.render()


def test_extension_is_flagged():
    o = parse_ordinanza(1, s.EXTENSION_BARI, "https://x")
    (msg, _), = views.notification_messages([o])
    assert "⏩ _chiusura prorogata_" in msg["blocks"][3]["text"]["text"]
    assert "📍 Puglia  ❓ _provincia non determinata_" in msg["blocks"][3]["text"]["text"]
