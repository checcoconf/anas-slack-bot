"""Secondo parere del modello locale: con un modello finto (prompt -> risposta), senza llama.cpp."""

from datetime import date

from anas_bot.ai import LocalModel
from anas_bot.anas.parser import CLOSURE
from anas_bot.listing_poller import ListingPoller
from tests.test_listing import _closure, _install, _rec, _riep

env = __import__('tests.test_listing', fromlist=['env']).env  # la fixture, riusata qui


def _fake(answers: dict[str, str]):
    """Risponde in base a una parola chiave contenuta nel prompt."""
    calls = []

    def generate(prompt: str) -> str:
        calls.append(prompt)
        for key, out in answers.items():
            if key in prompt:
                return out
        return "boh"
    generate.calls = calls
    return generate


def test_model_doubt_marks_a_closure_as_to_be_verified(env):
    cfg, db, listing, src = env
    p = ListingPoller(db, listing, src, cfg)
    _install(p, listing)
    p.ai = LocalModel("x.gguf", generate=_fake({
        "SS 719": "VERDETTO: non_chiusura\nMOTIVO: il divieto riguarda solo bici e ciclomotori, le auto passano",
        "SS 16": "VERDETTO: chiusura_totale\nMOTIVO: chiusura al traffico su tutte le corsie",
    }))
    listing.pages["BA"].insert(0, _closure(213900, "03/11/2026"))                       # SS 16: chiusura vera
    listing.pages["BA"].insert(0, _rec(213901, _riep("SS 719 PRATO - PISTOIA", "su <strong>tutte le corsie</strong>,",
                                                     ["chiusura al traffico"], "a partire dal <strong>03/11/2026</strong>"),
                                       numero="901/2026/BA"))
    r = p.run(date(2026, 11, 3))
    a, b = db.get_ordinanza(213900), db.get_ordinanza(213901)
    assert a.category == CLOSURE and not a.uncertain                                     # il modello conferma
    assert b.category == CLOSURE and b.uncertain and "modello locale dubita" in b.uncertain_why   # il modello dissente
    assert "bici" in r.uncertain and r.ai_calls == 2 or any("bici" in k for k in r.uncertain)
    # con AI_MODE=log i pareri restano nel log e non toccano i messaggi
    p2 = ListingPoller(db, listing, src, cfg)
    p2.ai, p2.ai_flag = p.ai, False
    listing.pages["BA"].insert(0, _rec(213902, _riep("SS 719 PRATO - PISTOIA", "su <strong>tutte le corsie</strong>,",
                                                     ["chiusura al traffico"], "a partire dal <strong>03/11/2026</strong>"),
                                       numero="902/2026/BA"))
    p2.run(date(2026, 11, 3))
    assert not db.get_ordinanza(213902).uncertain


def test_model_absorbs_harmless_new_measures_into_the_vocabulary(env):
    cfg, db, listing, src = env
    p = ListingPoller(db, listing, src, cfg)
    _install(p, listing)
    p.ai = LocalModel("x.gguf", generate=_fake({
        "«carretti a mano»": "CHIUSURA: no\nMOTIVO: è una categoria di utenti, non un provvedimento",
        "«sbarramento totale»": "CHIUSURA: si\nMOTIVO: potrebbe indicare una chiusura",
        "VERDETTO": "VERDETTO: chiusura_totale\nMOTIVO: ok",
    }))
    listing.pages["BA"].insert(0, _rec(213910, _riep("SS 100", "su <strong>corsia di marcia</strong>,",
                                                     ["divieto di transito", "carretti a mano"],
                                                     "a partire dal <strong>03/11/2026</strong>", users="velocipedi")))
    listing.pages["BA"].insert(0, _rec(213911, _riep("SS 101", "su <strong>corsia di marcia</strong>,",
                                                     ["sbarramento totale"], "a partire dal <strong>03/11/2026</strong>")))
    r = p.run(date(2026, 11, 3))
    assert "carretti a mano" in r.learned and "carretti a mano" not in r.unknown     # innocua: imparata
    assert "sbarramento totale" in r.unknown and "sbarramento totale" not in r.learned   # sospetta: avviso come prima
    assert "carretti a mano" in db.get("learned_measures")
    # al giro dopo la voce imparata non è più "nuova"
    listing.pages["BA"].insert(0, _rec(213912, _riep("SS 100", "su <strong>corsia di marcia</strong>,",
                                                     ["divieto di transito", "carretti a mano"],
                                                     "a partire dal <strong>04/11/2026</strong>", users="velocipedi")))
    r = p.run(date(2026, 11, 4))
    assert "carretti a mano" not in r.unknown and "carretti a mano" not in r.learned


def test_model_failures_never_break_the_run(env):
    cfg, db, listing, src = env
    p = ListingPoller(db, listing, src, cfg)
    _install(p, listing)

    def broken(prompt):
        raise RuntimeError("modello esploso")
    p.ai = LocalModel("x.gguf", generate=broken)
    listing.pages["BA"].insert(0, _closure(213920, "03/11/2026"))
    r = p.run(date(2026, 11, 3))
    assert r.new == 1 and not r.error and not db.get_ordinanza(213920).uncertain
    p.ai = LocalModel("x.gguf", generate=lambda prompt: "risposta a caso senza formato")
    listing.pages["BA"].insert(0, _closure(213921, "03/11/2026"))
    r = p.run(date(2026, 11, 3))
    assert r.new == 1 and not db.get_ordinanza(213921).uncertain
    assert LocalModel.from_env("off", "x.gguf") is None and LocalModel.from_env("flag", "/non/esiste.gguf") is None
