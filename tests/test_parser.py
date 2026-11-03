from datetime import date

from anas_bot.anas.parser import CLOSURE, OTHER, REOPENING, SPEED, UNREADABLE, parse_ordinanza
from tests import samples as s


def test_closure_full_road():
    o = parse_ordinanza(1, s.CLOSURE_SS614)
    assert o.category == CLOSURE
    assert o.roads[0] == "SS614"
    assert o.road_names.get("SS614") == "della Maielletta"
    assert (o.km_from, o.km_to) == ("12+300", "14+050")
    assert o.start_date == "2026-11-10" and o.end_date == "2026-11-14"
    assert o.time_window == "08:00-17:00"
    assert o.provinces == ["CH", "PE"]
    assert o.regions == ["abruzzo"]
    assert o.number == "266/2026"
    assert o.structure == "Abruzzo e Molise"
    assert not o.ramp_only


def test_ramp_closure_on_motorway():
    o = parse_ordinanza(2, s.RAMP_A2)
    assert o.category == CLOSURE
    assert o.ramp_only
    assert o.roads[0] == "A2"
    assert o.km_from == "187+748"
    assert o.provinces == ["CS"]
    assert o.time_window == "22:00-07:00"


def test_lane_closure_is_ignored():
    assert parse_ordinanza(3, s.LANE_ONLY).category == OTHER


def test_mixed_lane_and_ramp_counts_as_closure():
    o = parse_ordinanza(4, s.MIXED_LANE_AND_CLOSURE)
    assert o.category == CLOSURE
    assert o.ramp_only
    assert o.km_from == "452+300"
    assert o.time_window == "21:00-06:00"


def test_truck_only_restriction_is_ignored():
    assert parse_ordinanza(5, s.TRUCKS_ONLY).category == OTHER


def test_permanent_speed_limit():
    o = parse_ordinanza(6, s.SPEED_PERMANENT)
    assert o.category == SPEED
    assert o.speed_kmh == 70
    assert o.provinces == ["FG"] and o.regions == ["puglia"]
    assert o.start_date == "2026-11-15" and o.open_ended


def test_worksite_speed_limit_is_ignored():
    assert parse_ordinanza(7, s.SPEED_WORKSITE).category == OTHER


def test_reopening():
    o = parse_ordinanza(8, s.REOPENING_SS36)
    assert o.category == REOPENING
    assert "SS36" in o.roads
    assert o.provinces == ["LC"]


def test_region_from_structure_when_no_province():
    o = parse_ordinanza(9, s.NO_PROVINCE)
    assert o.category == CLOSURE
    assert o.provinces == []
    assert o.regions == ["sardegna"]
    assert not o.province_inferred


def test_expired():
    o = parse_ordinanza(10, s.EXPIRED)
    assert o.is_expired(date(2026, 11, 1))
    assert not parse_ordinanza(1, s.CLOSURE_SS614).is_expired(date(2026, 11, 1))


def test_unreadable_pdf():
    assert parse_ordinanza(11, "   ").category == UNREADABLE


def test_speed_value_not_taken_as_motorway():
    o = parse_ordinanza(6, s.SPEED_PERMANENT)
    assert not any(r.startswith("A") for r in o.roads)


def test_direction():
    assert parse_ordinanza(1, s.CLOSURE_SS614).direction == "entrambe le direzioni"
    assert parse_ordinanza(2, s.RAMP_A2).direction == "carreggiata Nord"


def test_2026_format_number_structure_city_and_extension():
    o = parse_ordinanza(213467, s.EXTENSION_BARI)
    assert o.category == CLOSURE
    assert o.extension
    assert o.number == "723/2026/BA"
    assert o.structure == "Bari"
    assert o.regions == ["puglia"] and o.provinces == []  # nessuna prefettura citata: regione dalla struttura
    assert o.roads[0] == "SS172"
    assert o.end_date == "2026-11-20"


def test_region_from_number_suffix_when_structure_missing():
    from anas_bot.anas.parser import regions_from_structure
    assert regions_from_structure("", "CT") == ["sicilia"]
    assert regions_from_structure("Abruzzo e Molise") == ["abruzzo", "molise"]


def test_closure_of_a_rest_area_is_not_a_closure_for_waze():
    """PDF reale (SS 18 VAR Cilentana, 03/11/2026): chiusa la piazzola di sosta, la strada resta aperta."""
    from anas_bot.anas.parser import OTHER, parse_ordinanza
    text = ("ORDINANZA N°800/2026/NA\nORDINA\n* chiusura al traffico su SS 18 VAR CILENTANA dal km 133+900 "
            "al km 134+000, Sapri, su piazzola di sosta a partire dalle ore 00:00 del 3/11/2026 fino alle ore "
            "24:00 del 30/12/2026 esclusi i giorni festivi; interesserà tutti gli utenti.")
    assert parse_ordinanza(214100, text, "u").category == OTHER


def test_closure_of_a_service_area_is_reported_as_access_closure():
    """Un'area di servizio chiusa va segnalata (in Waze ha le sue rampe), ma come accesso, non come strada."""
    from anas_bot.anas.parser import CLOSURE, parse_ordinanza
    text = ("ORDINANZA N°801/2026/NA\nORDINA\n* chiusura al traffico su A2 AUTOSTRADA DEL MEDITERRANEO dal km "
            "10+000 al km 10+500, area di servizio Sala Consilina ovest, a partire dalle ore 00:00 del 3/11/2026 "
            "fino alle ore 24:00 del 30/12/2026; interesserà tutti gli utenti.")
    o = parse_ordinanza(214101, text, "u")
    assert o.category == CLOSURE and o.ramp_only


def test_closure_from_pdf_without_whole_carriageway_is_flagged():
    from anas_bot.anas.parser import CLOSURE, parse_ordinanza
    text = ("ORDINANZA N°802/2026/BA\nORDINA\n* chiusura al traffico su SS 16 dal km 10+000 al km 12+000, "
            "Bari, su piattaforma galleggiante a partire dalle ore 00:00 del 3/11/2026; interesserà tutti gli utenti.")
    o = parse_ordinanza(214102, text, "u")
    assert o.category == CLOSURE and o.uncertain
    whole = ("ORDINANZA N°803/2026/BA\nORDINA\n* chiusura al traffico su SS 16 dal km 10+000 al km 12+000 "
             "su tutte le corsie a partire dalle ore 00:00 del 3/11/2026; interesserà tutti gli utenti.")
    assert not parse_ordinanza(214103, whole, "u").uncertain
