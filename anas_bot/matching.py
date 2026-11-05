"""Chi deve ricevere una certa ordinanza."""

from __future__ import annotations

from .anas.parser import CLOSURE, REOPENING, SPEED, Ordinanza
from .db import User
from .geo import MOTORWAYS, PROVINCE_BY_CODE


def wants_category(user: User, o: Ordinanza) -> bool:
    if o.category in (CLOSURE, REOPENING):
        return user.want_closures
    if o.category == SPEED:
        return user.want_speed
    return user.want_all  # cantieri, restringimenti, sensi unici, limiti temporanei...


def in_zones(o: Ordinanza, all_italy: bool, regions: list[str], provinces: list[str],
             unknown_province_fallback: bool = True) -> bool:
    """L'ordinanza ricade in queste zone?

    - "Tutta Italia" prende tutto.
    - "Autostrade (tutta Italia)" prende ogni ordinanza su A* e RA*, in qualunque regione.
    - Una regione scelta copre tutte le sue province.
    - Una provincia scelta prende le ordinanze che citano quella provincia.
    - Se dall'ordinanza non si ricava la provincia (solo la regione), chi ha scelto una provincia di
      quella regione la riceve comunque, segnalata come "provincia non determinata": meglio un avviso
      in più che una chiusura persa.
    """
    if all_italy:
        return True
    if MOTORWAYS in regions and o.motorway:
        return True
    if set(o.regions) & set(regions):
        return True
    if set(o.provinces) & set(provinces):
        return True
    if not o.provinces and unknown_province_fallback:
        regions_from_prov = {PROVINCE_BY_CODE[p].region for p in provinces if p in PROVINCE_BY_CODE}
        return bool(regions_from_prov & set(o.regions))
    return False


def matches(user: User, o: Ordinanza, unknown_province_fallback: bool = True) -> bool:
    """True se l'ordinanza è del tipo che l'utente vuole e ricade nelle sue zone.

    Le ordinanze "altre" (cantieri, restringimenti...) hanno zone proprie, se l'utente le ha scelte:
    si può seguire tutta Italia per le chiusure e una sola provincia per i cantieri. Zone dei cantieri
    vuote = le stesse zone delle chiusure."""
    if not user.receives or not wants_category(user, o):
        return False
    if o.category not in (CLOSURE, REOPENING, SPEED) and (user.all_regions or user.all_provinces):
        return in_zones(o, False, user.all_regions, user.all_provinces, unknown_province_fallback)
    return in_zones(o, user.all_italy, user.regions, user.provinces, unknown_province_fallback)
