"""Secondo parere del modello locale: con un modello finto (prompt -> risposta), senza llama.cpp."""

import json
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


def test_model_estimates_the_province_by_day_and_saves_the_pdf_request(env):
    """Di giorno: atlante vuoto -> il modello stima la provincia (certezza alta, dentro la regione) -> niente PDF.
    Con certezza media si legge il PDF. Una sigla fuori regione non si accetta."""
    cfg, db, listing, src = env
    cfg.max_pdf_per_run_day = 1
    p = ListingPoller(db, listing, src, cfg)
    _install(p, listing)
    answers = {
        "strada: SS268": "PROVINCE: NA\nCERTEZZA: alta\nMOTIVO: il raccordo del Vesuvio è interamente in provincia di Napoli",
        "strada: SS16": "PROVINCE: BA, BT\nCERTEZZA: media\nMOTIVO: la SS 16 attraversa più province",
        "strada: SS999": "PROVINCE: MI\nCERTEZZA: alta\nMOTIVO: sbagliato di proposito",
        "VERDETTO": "VERDETTO: chiusura_totale\nMOTIVO: ok",
    }
    p.ai = LocalModel("x.gguf", generate=_fake(answers))
    src.docs.update({214200: "ALLA PREFETTURA DI BARI\nchiusura", 214201: "ALLA PREFETTURA DI FOGGIA\nchiusura"})
    listing.pages["BA"].insert(0, _rec(214200, _riep("SS 268 DEL VESUVIO", "su <strong>tutte le corsie</strong>,", ["chiusura al traffico"],
                                                     "a partire dal <strong>03/11/2026</strong>")))
    p.run(date(2026, 11, 3), hour=14)
    o = db.get_ordinanza(214200)
    # la struttura è Bari (Puglia): NA è fuori regione -> stima rifiutata -> PDF -> Bari
    assert o.provinces == ["BA"] and not o.province_guessed and src.requests == [214200]
    listing.pages["BA"].insert(0, _closure(214201, "03/11/2026"))               # SS 16: certezza media -> PDF
    p.run(date(2026, 11, 3), hour=14)
    assert db.get_ordinanza(214201).provinces == ["FG"] and src.requests == [214200, 214201]
    listing.pages["MI"].insert(0, _rec(214202, _riep("SS 999 DI PROVA", "su <strong>tutte le corsie</strong>,", ["chiusura al traffico"],
                                                     "a partire dal <strong>03/11/2026</strong>"), numero="9/2026/MI"))
    p.run(date(2026, 11, 3), hour=14)
    o3 = db.get_ordinanza(214202)
    assert o3.provinces == ["MI"] and o3.province_guessed and src.requests == [214200, 214201]   # stima accettata, niente PDF


def test_other_ordinances_for_province_followers_use_atlas_and_model_before_the_night_pdf(env):
    """"Altre ordinanze" seguite per provincia: se il modello è sicuro, partono di giorno senza aspettare il PDF."""
    cfg, db, listing, src = env
    p = ListingPoller(db, listing, src, cfg)
    _install(p, listing)
    db.ensure_user("U_TA")
    db.save_preferences("U_TA", all_italy=True, regions=[], provinces=[], want_closures=True, want_speed=True,
                        want_all=True, all_provinces=["TA"])
    p.ai = LocalModel("x.gguf", generate=_fake({
        "strada: SS7": "PROVINCE: TA\nCERTEZZA: alta\nMOTIVO: la SS 7 Appia nel tratto finale è in provincia di Taranto",
        "strada: SS16": "PROVINCE: BA, BT\nCERTEZZA: bassa\nMOTIVO: attraversa più province",
    }))
    works = lambda i, road: _rec(i, _riep(road, "su <strong>corsia di marcia</strong>,", ["restringimento carreggiata"],  # noqa: E731
                                          "a partire dal <strong>03/11/2026</strong> fino al <strong>30/11/2026</strong>"))
    listing.pages["BA"].insert(0, works(214300, "SS 7 APPIA"))
    listing.pages["BA"].insert(0, works(214301, "SS 16 ADRIATICA"))
    r = p.run(date(2026, 11, 3), hour=14)
    assert r.new == 1 and r.deferred == 1 and src.requests == []            # SS 7: stimata TA, parte; SS 16: aspetta la notte
    assert db.get_ordinanza(214300).provinces == ["TA"] and db.get_ordinanza(214301) is None


def test_model_calls_are_capped_per_run():
    from anas_bot import ai as AI
    m = LocalModel("x.gguf", generate=lambda prompt: "VERDETTO: chiusura_totale\nMOTIVO: ok")
    for _ in range(AI.MAX_CALLS_PER_RUN):
        assert m.closure_verdict("testo") is not None
    assert m.closure_verdict("testo") is None                 # oltre il tetto: nessun parere, nessun errore
    slow = LocalModel("x.gguf", generate=lambda prompt: "VERDETTO: chiusura_totale\nMOTIVO: ok")
    slow.seconds = AI.MAX_SECONDS_PER_RUN
    assert slow.closure_verdict("testo") is None


def test_model_crash_disables_it_for_the_run(monkeypatch):
    """Il processo del modello crolla (es. istruzione illegale): parere None e da lì solo regole, mai un'eccezione."""
    from anas_bot import ai as ai_mod
    m = ai_mod.LocalModel("x.gguf")
    calls = []

    def crashed(prompt):
        calls.append(prompt)
        raise ai_mod.ModelCrashed("uscita -4: Illegal instruction")
    monkeypatch.setattr(m, "_in_subprocess", crashed)
    assert m.closure_verdict("testo") is None
    assert m.disabled is True
    assert m.closure_verdict("altro testo") is None
    assert len(calls) == 1  # dopo il crollo non si riprova più nel giro


def test_model_timeout_disables_it_for_the_run(monkeypatch):
    import subprocess
    from anas_bot import ai as ai_mod
    m = ai_mod.LocalModel("x.gguf")

    def hung(prompt):
        raise subprocess.TimeoutExpired(cmd="x", timeout=1)
    monkeypatch.setattr(m, "_in_subprocess", hung)
    assert m.closure_verdict("testo") is None
    assert m.disabled is True


def test_model_subprocess_protocol(monkeypatch):
    """Il figlio riceve il JSON e la risposta torna com'è; uscita diversa da 0 -> ModelCrashed."""
    import subprocess
    from anas_bot import ai as ai_mod
    m = ai_mod.LocalModel("x.gguf", n_threads=2)
    seen = {}

    def fake_run(args, input, capture_output, text, timeout):
        seen["req"] = json.loads(input)
        seen["args"] = args
        return subprocess.CompletedProcess(args, 0, stdout="VERDETTO: non_chiusura\nMOTIVO: solo bici", stderr="")
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert m.closure_verdict("testo") == ("non_chiusura", "solo bici")
    assert seen["req"]["model_path"] == "x.gguf" and seen["req"]["n_threads"] == 2
    assert seen["args"][-2:] == ["-m", "anas_bot.ai_worker"]

    def fake_crash(args, input, capture_output, text, timeout):
        return subprocess.CompletedProcess(args, -4, stdout="", stderr="Illegal instruction (core dumped)")
    monkeypatch.setattr(subprocess, "run", fake_crash)
    assert m.closure_verdict("testo") is None and m.disabled
