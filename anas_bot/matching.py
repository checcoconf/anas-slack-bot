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
    return False


def matches(user: User, o: Ordinanza, unknown_province_fallback: bool = True) -> bool:
    """True se l'ordinanza ricade nelle zone scelte dall'utente.

    - "Tutta Italia" riceve tutto.
    - "Autostrade (tutta Italia)" riceve ogni ordinanza su A* e RA*, in qualunque regione.
    - Una regione scelta copre tutte le sue province.
    - Una provincia scelta riceve le ordinanze che citano quella provincia.
    - Se dall'ordinanza non si ricava la provincia (solo la regione), chi ha
      scelto una provincia di quella regione la riceve comunque, segnalata come
      "provincia non determinata": meglio un avviso in più che una chiusura persa.
    """
    if not user.receives or not wants_category(user, o):
        return False
    if user.all_italy:
        return True
    if MOTORWAYS in user.regions and o.motorway:
        return True
    if set(o.regions) & set(user.regions):
        return True
    if set(o.provinces) & set(user.provinces):
        return True
    if not o.provinces and unknown_province_fallback:
        user_regions_from_prov = {PROVINCE_BY_CODE[p].region for p in user.provinces if p in PROVINCE_BY_CODE}
        return bool(user_regions_from_prov & set(o.regions))
    return False
