"""Tutta Italia, zona per zona: ogni ordinanza ANAS arriva a chi segue la sua regione o una sua provincia.

Per ognuna delle 23 strutture ANAS: una chiusura e un'altra ordinanza appena pubblicate, senza provincia nel
riepilogo (il caso più comune), lette di giorno e consegnate nello stesso giro. Devono arrivare a chi segue
ogni provincia delle regioni della struttura e a chi segue la regione; mai a chi segue altre zone.
Poi, per ognuna delle 107 province, le regole di consegna con la provincia nota e non nota.
"""

from __future__ import annotations

from datetime import date

import pytest

from anas_bot.anas.listing import KNOWN_STRUCTURES, STRUCTURE_REGIONS, Structure
from anas_bot.anas.parser import CLOSURE, OTHER, Ordinanza
from anas_bot.config import Config
from anas_bot.db import Database
from anas_bot.geo import PROVINCES, PROVINCE_BY_CODE
from anas_bot.listing_poller import ListingPoller
from anas_bot.matching import matches
from anas_bot.notifier import Notifier
from tests.fakes import FakeSlack
from tests.test_listing import FakeListing, FakeSource, _closure, _rec, _riep

LABELS = dict(KNOWN_STRUCTURES)
TODAY = date(2026, 11, 17)


class _Listing(FakeListing):
    def structures(self, day=None):
        return [Structure(c, LABELS[c]) for c in self.pages]


def _provinces_of(regions: list[str]) -> list[str]:
    return [p.code for p in PROVINCES if p.region in regions]


def _outsider(regions: list[str]) -> str:
    return next(p.code for p in PROVINCES if p.region not in regions and p.region != "trentino-alto-adige")


def _follow(db, uid, *, closures=False, others=False, provinces=(), regions=(), all_italy=False):
    db.ensure_user(uid)
    if others:  # solo le "altre ordinanze", con zone proprie
        db.save_preferences(uid, all_italy=False, regions=[], provinces=[], want_closures=False, want_speed=False,
                            want_all=True, all_regions=list(regions), all_provinces=list(provinces))
    else:
        db.save_preferences(uid, all_italy=all_italy, regions=list(regions), provinces=list(provinces),
                            want_closures=closures, want_speed=False)


@pytest.mark.parametrize("code", sorted(STRUCTURE_REGIONS))
def test_every_structure_reaches_every_province_and_region(tmp_path, code):
    regions = STRUCTURE_REGIONS[code]
    db = Database.local(str(tmp_path / f"{code}.sqlite3"))
    cfg = Config()
    cfg.max_pdf_per_run_day = 0  # nessun PDF: la provincia non si conosce, il caso peggiore
    old = [_closure(100 + i, "20/10/2026", numero=f"{100 + i}/2026/{code}") for i in range(6)]
    listing = _Listing({code: old})
    src = FakeSource({})
    p = ListingPoller(db, listing, src, cfg)
    p.run(date(2026, 11, 1))  # installazione: tutto ciò che c'è è "vecchio"

    provinces = _provinces_of(regions)
    out = _outsider(regions)
    for prov in provinces:
        _follow(db, f"C_{prov}", closures=True, provinces=[prov])
        _follow(db, f"A_{prov}", others=True, provinces=[prov])
    for reg in regions:
        _follow(db, f"C_{reg}", closures=True, regions=[reg])
        _follow(db, f"A_{reg}", others=True, regions=[reg])
    _follow(db, "C_IT", closures=True, all_italy=True)
    _follow(db, "C_OUT", closures=True, provinces=[out])
    _follow(db, "A_OUT", others=True, provinces=[out])

    period = "a partire dal <strong>17/11/2026</strong> fino al <strong>30/11/2026</strong>"
    closure = _rec(216001, _riep("SS 106 JONICA", "su <strong>tutte le corsie</strong>,", ["chiusura al traffico"], period),
                   numero=f"801/2026/{code}")
    other = _rec(216002, _riep("SS 106 JONICA", "sulla <strong>corsia di marcia</strong>,",
                               ["senso unico alternato mediante impianto semaforico o movieri",
                                "restringimento carreggiata destra"], period), numero=f"802/2026/{code}")
    listing.pages[code][:0] = [closure, other]
    r = p.run(TODAY, hour=12)
    assert r.new == 2 and r.deferred == 0 and src.requests == []      # trovate subito, nessuna attesa

    slack = FakeSlack()
    Notifier(db, slack).run(TODAY)
    got: dict[str, str] = {}
    for post in slack.posts:
        got.setdefault(post["channel"].removeprefix("D-"), "")
        got[post["channel"].removeprefix("D-")] += str(post)

    closure_to = {f"C_{x}" for x in [*provinces, *regions]} | {"C_IT"}
    other_to = {f"A_{x}" for x in [*provinces, *regions]}
    for uid in closure_to:
        assert f"801/2026/{code}" in got.get(uid, ""), f"chiusura {code} non arrivata a {uid}"
        assert f"802/2026/{code}" not in got.get(uid, ""), f"cantiere {code} a chi non lo vuole ({uid})"
    for uid in other_to:
        assert f"802/2026/{code}" in got.get(uid, ""), f"altra ordinanza {code} non arrivata a {uid}"
        assert f"801/2026/{code}" not in got.get(uid, ""), f"chiusura {code} a chi segue solo i lavori ({uid})"
    assert "C_OUT" not in got and "A_OUT" not in got, f"{code}: arrivata fuori zona"


PROVINCE_CODES = [p.code for p in PROVINCES]


@pytest.mark.parametrize("prov", PROVINCE_CODES)
def test_every_province_known_or_not(tmp_path, prov):
    region = PROVINCE_BY_CODE[prov].region
    same_region = [p for p in _provinces_of([region]) if p != prov]
    out = _outsider([region])
    db = Database.local(str(tmp_path / "p.sqlite3"))
    for uid, kw in {"P": dict(closures=True, provinces=[prov]), "R": dict(closures=True, regions=[region]),
                    "OUT": dict(closures=True, provinces=[out]), "AP": dict(others=True, provinces=[prov]),
                    "AR": dict(others=True, regions=[region]), "AOUT": dict(others=True, provinces=[out])}.items():
        _follow(db, uid, **kw)
    if same_region:
        _follow(db, "SAME", closures=True, provinces=[same_region[0]])
        _follow(db, "ASAME", others=True, provinces=[same_region[0]])
    u = {x.user_id: x for x in db.all_users()}

    for cat, (follower, region_f, outsider, same) in ((CLOSURE, ("P", "R", "OUT", "SAME")),
                                                     (OTHER, ("AP", "AR", "AOUT", "ASAME"))):
        known = Ordinanza(ord_id=1, category=cat, regions=[region], provinces=[prov])
        unknown = Ordinanza(ord_id=2, category=cat, regions=[region], provinces=[])
        # provincia nota: la provincia e la regione sì, un'altra provincia della stessa regione no, fuori zona no
        assert matches(u[follower], known) and matches(u[region_f], known) and not matches(u[outsider], known)
        if same in u:
            assert not matches(u[same], known)
        # provincia non nota: arriva a chiunque segua una provincia della regione ("nel dubbio arriva")
        assert matches(u[follower], unknown) and matches(u[region_f], unknown) and not matches(u[outsider], unknown)
        if same in u:
            assert matches(u[same], unknown)
