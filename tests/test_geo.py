from anas_bot.geo import PROVINCES, REGIONS, find_provinces, find_regions, provinces_of_region


def test_counts():
    assert len(REGIONS) == 20
    assert len(PROVINCES) == 110
    assert {p.code for p in provinces_of_region("sardegna")} == {"SS", "NU", "CA", "OR", "OT", "OG", "VS", "SU"}


def test_find_provinces_with_context():
    text = """AL COMANDO PROVINCIALE DEI CARABINIERI DI L'AQUILA
    Prefettura dell'Aquila, Questura di Reggio Calabria, in provincia di Forlì-Cesena,
    Città Metropolitana di Roma Capitale, Libero Consorzio Comunale di Agrigento"""
    assert find_provinces(text) == ["AG", "AQ", "FC", "RC", "RM"]


def test_bare_place_names_are_not_provinces():
    # "Prato" e "Massa" come località, senza "provincia di" / "prefettura di" davanti
    assert find_provinces("svincolo di Prato Sesia, località Massa Lubrense, comune di Bari Sardo") == []


def test_legacy_sud_sardegna():
    assert find_provinces("Provincia del Sud Sardegna") == ["SU", "VS"]


def test_find_regions():
    assert find_regions("Struttura Territoriale Piemonte e Valle d'Aosta") == ["piemonte", "valle-d-aosta"]
    assert find_regions("Abruzzo e Molise") == ["abruzzo", "molise"]


def test_motorways_zone_matches_any_motorway_anywhere():
    from anas_bot.anas.parser import CLOSURE, Ordinanza
    from anas_bot.db import User
    from anas_bot.geo import MOTORWAYS
    from anas_bot.matching import matches
    a19 = Ordinanza(ord_id=1, category=CLOSURE, roads=["A19"], regions=["sicilia"], provinces=["PA"])
    ra6 = Ordinanza(ord_id=2, category=CLOSURE, roads=["RA6"], regions=["umbria"], provinces=["PG"])
    ss16 = Ordinanza(ord_id=3, category=CLOSURE, roads=["SS16"], regions=["puglia"], provinces=["BA"])
    u = User("U1", configured=True, regions=[MOTORWAYS, "puglia"])
    assert matches(u, a19) and matches(u, ra6) and matches(u, ss16)
    only_puglia = User("U2", configured=True, regions=["puglia"])
    assert not matches(only_puglia, a19) and matches(only_puglia, ss16)
    assert a19.motorway and ra6.motorway and not ss16.motorway
