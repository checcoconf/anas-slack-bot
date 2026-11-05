"""Prova dei filtri di data della ricerca di Ordinanze Web — da lanciare sul TUO computer.

Domanda: cosa fanno "data_validita_inizio" e "data_validita_fine"? Se con fine = domani la prima
pagina mostra le ordinanze che PARTONO oggi o domani (invece di quelle che partono tra settimane),
il bot può trovare di giorno, in una pagina sola, proprio le ordinanze fresche.

Fa 5 richieste oneste in tutto (pagina + 4 ricerche sulla struttura BA), con 15 secondi di pausa.

    python -m collaudo.filtro_date
"""

from __future__ import annotations

import datetime
import os
import random
import string
import time

import requests

SITE = "https://www.stradeanas.it"
PAGE = SITE + "/it/ordinanze-web"
SEARCH = SITE + "/anas_ordinanzeweb/searchordinanze"
UA = os.environ.get("ANAS_USER_AGENT", "WazeItaliaAnasBot")
TIMEOUT = (10, 30)
PAUSA = 15
STRUTTURA = os.environ.get("STRUTTURA", "BA")


def cerca(s: requests.Session, inizio: str, fine: str) -> dict:
    data = {"action": "search_ordinanze", "page": "1", "causa": "*", "causa_dett": "*",
            "area_compartimentale": STRUTTURA, "strada": "*", "numero_ordinanza": "", "limitazioni": "*",
            "data_validita_inizio": inizio, "data_validita_fine": fine,
            "random": "".join(random.choices(string.ascii_letters, k=5))}
    r = s.post(SEARCH, data=data, timeout=TIMEOUT, headers={
        "Accept": "application/json, text/javascript, */*; q=0.01", "X-Requested-With": "XMLHttpRequest",
        "Origin": SITE, "Referer": PAGE})
    print(f"  HTTP {r.status_code}", end="")
    try:
        return r.json()
    except ValueError:
        print("  (risposta non JSON)", r.text[:200])
        return {}


def mostra(body: dict) -> None:
    print(f"  totale: {body.get('tot_record')}  pagine: {body.get('tot_pagine')}  esito: {body.get('esito')}")
    for rec in body.get("results") or []:
        print(f"    ID {rec.get('ID')}  {rec.get('TIPO_ORDINANZA'):<10} n. {rec.get('NUMERO_ORDINANZA'):<16} "
              f"validita {rec.get('VALIDITA_MIN') or '?'} -> {rec.get('VALIDITA_MAX') or '?'}  proroga {rec.get('PROROGA_DATA') or '-'}")


def main() -> int:
    oggi = datetime.date.today()
    domani = oggi + datetime.timedelta(days=1)
    tra7 = oggi + datetime.timedelta(days=7)
    print("=" * 70)
    print(f" Filtri di data della ricerca — struttura {STRUTTURA} — {oggi:%d/%m/%Y}")
    print("=" * 70)
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "it-IT,it;q=0.9"})
    r = s.get(PAGE, timeout=TIMEOUT)
    print(f"pagina: HTTP {r.status_code}")
    prove = [
        ("A) come il bot oggi: inizio=oggi, fine=vuoto", oggi.isoformat(), ""),
        ("B) inizio=oggi, fine=domani", oggi.isoformat(), domani.isoformat()),
        ("C) inizio=domani, fine=domani", domani.isoformat(), domani.isoformat()),
        ("D) inizio=oggi, fine=tra 7 giorni", oggi.isoformat(), tra7.isoformat()),
    ]
    for titolo, inizio, fine in prove:
        time.sleep(PAUSA)
        print(f"\n{titolo}")
        mostra(cerca(s, inizio, fine))
    print("\nFatto. Trascina collaudo\\risultati\\filtro_date.log nella chat.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
