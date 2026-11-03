"""Diagnosi "sono bloccato da ANAS?" — da lanciare sul TUO computer.

Fa pochissime richieste ONESTE e una sola volta ciascuna:
  1) /robots.txt   2) la pagina delle ordinanze   3) una ricerca
con lo User-Agent che dichiara chi sei, rispettando il robots.txt. Se trova un blocco
NON ritenta e si ferma. Serve solo a capire, in pochi secondi, se il tuo indirizzo è
bloccato dal firewall di ANAS in questo momento: non raccoglie ordinanze e non aggira nulla.

    python -m collaudo.diagnosi
"""

from __future__ import annotations

import datetime
import os
import sys
import time
from urllib.robotparser import RobotFileParser

import requests

SITE = "https://www.stradeanas.it"
PAGE = SITE + "/it/ordinanze-web"
SEARCH = SITE + "/anas_ordinanzeweb/searchordinanze"
ROBOTS = SITE + "/robots.txt"
UA = os.environ.get("ANAS_USER_AGENT", "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:159.0) Gecko/20100101 Firefox/159.0")
TIMEOUT = (10, 30)
BLOCK_MARKERS = ("web page blocked", "the url you requested has been blocked", "attack id")


def _blocked(text: str) -> bool:
    low = (text or "").lower()
    return any(m in low for m in BLOCK_MARKERS)


def _attack_id(text: str) -> str:
    for line in (text or "").splitlines():
        if "attack id" in line.lower():
            return " ".join(line.split())
    return ""


def main() -> int:
    print("=" * 60)
    print(" Diagnosi accesso ANAS —", datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
    print(" User-Agent:", UA)
    print("=" * 60)
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "it-IT,it;q=0.9"})
    blocked = False

    # 1) robots.txt — da crawler educato, prima di tutto
    try:
        r = s.get(ROBOTS, timeout=TIMEOUT)
        rp = RobotFileParser()
        rp.parse(r.text.splitlines() if r.status_code == 200 else [])
        page_ok = rp.can_fetch(UA, PAGE)
        search_ok = rp.can_fetch(UA, SEARCH)
        print(f"\n[1/3] robots.txt  -> HTTP {r.status_code}")
        print(f"      pagina ordinanze consentita: {'si' if page_ok else 'NO'}")
        print(f"      ricerca consentita:          {'si' if search_ok else 'NO'}")
        if r.status_code == 200 and not (page_ok and search_ok):
            print("      ATTENZIONE: il robots.txt ora vieta queste pagine. Mi fermo per rispetto delle regole.")
            return 2
    except requests.RequestException as exc:
        print(f"\n[1/3] robots.txt  -> non raggiungibile: {exc}")
        print("      Sito irraggiungibile (rete, DNS o sito giu'). Riprova piu' tardi.")
        return 3

    time.sleep(3)  # pausa educata tra una richiesta e l'altra

    # 2) pagina delle ordinanze (una sola richiesta)
    try:
        r = s.get(PAGE, timeout=TIMEOUT)
        if _blocked(r.text):
            blocked = True
            print(f"\n[2/3] pagina ordinanze -> BLOCCATO (HTTP {r.status_code})  {_attack_id(r.text)}")
        else:
            print(f"\n[2/3] pagina ordinanze -> OK (HTTP {r.status_code}, {len(r.text)} byte)")
    except requests.RequestException as exc:
        print(f"\n[2/3] pagina ordinanze -> errore di rete: {exc}")
        return 3

    time.sleep(3)

    # 3) una sola ricerca (l'endpoint che prima veniva bloccato per primo)
    try:
        today = datetime.date.today().isoformat()
        data = {"action": "search_ordinanze", "page": "1", "causa": "*", "causa_dett": "*",
                "area_compartimentale": "BA", "strada": "*", "numero_ordinanza": "",
                "limitazioni": "*", "data_validita_inizio": today, "data_validita_fine": "", "random": "abcde"}
        headers = {"X-Requested-With": "XMLHttpRequest", "Origin": SITE, "Referer": PAGE,
                   "Accept": "application/json, text/javascript, */*; q=0.01"}
        r = s.post(SEARCH, data=data, headers=headers, timeout=TIMEOUT)
        if _blocked(r.text):
            blocked = True
            print(f"[3/3] ricerca ordinanze -> BLOCCATO (HTTP {r.status_code})  {_attack_id(r.text)}")
        elif r.status_code == 200 and r.headers.get("Content-Type", "").startswith("application/json"):
            try:
                tot = r.json().get("tot_record", "?")
            except Exception:  # noqa: BLE001
                tot = "?"
            print(f"[3/3] ricerca ordinanze -> OK (HTTP {r.status_code}, {tot} ordinanze trovate)")
        else:
            print(f"[3/3] ricerca ordinanze -> risposta inattesa (HTTP {r.status_code}, "
                  f"{r.headers.get('Content-Type', '?')})")
    except requests.RequestException as exc:
        print(f"[3/3] ricerca ordinanze -> errore di rete: {exc}")
        return 3

    print("\n" + "=" * 60)
    if blocked:
        print(" ESITO: ⛔ SEI ANCORA BLOCCATO dal firewall di ANAS.")
        print(" Non rilanciare in continuazione: ogni tentativo allunga il blocco.")
        print(" Aspetta la risposta alla richiesta che hai inviato ad ANAS.")
    else:
        print(" ESITO: ✅ L'accesso al sito, dal tuo indirizzo, al momento funziona.")
        print(" Nota: questo dice solo che il TUO IP non e' bloccato adesso.")
        print(" Non dice che il bot (da Cloudflare, automatico) passerebbe: quello")
        print(" dipende comunque dall'autorizzazione di ANAS.")
    print("=" * 60)
    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(main())
