"""Collaudo della ricerca "tutta Italia" (area_compartimentale="*").

ESITO NOTO (03/11/2026): il sito risponde esito=false, "raggiunto il limite massimo di ordinanze
recuperabili" (3.911 in vigore, limite 1.000) e non elenca nulla. Per questo il bot legge le strutture
a rotazione. Questo collaudo resta per riprovare in futuro, se ANAS cambiasse il limite.

Due richieste in tutto (pagina del sito + ricerca), con lo stesso User-Agent del bot. Stampa:
- tot_record / tot_pagine dichiarati dal sito e quanti risultati arrivano davvero;
- per ogni risultato: ID, numero, struttura, tipo, data di inizio dal riepilogo.
Così si vede se il sito elenca davvero tutta Italia e in che ordine (per ID = per pubblicazione,
per data di inizio = per validità). Salva la risposta grezza in collaudo/risultati/italia.json.

    python -m collaudo.italia            # pagina 1
    python -m collaudo.italia --pagine 2 # pagine 1 e 2 (una richiesta in più)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from anas_bot.anas.client import AnasClient, BlockedError, TransientError
from anas_bot.anas.listing import ITALY, ListingClient, ListingError, _START

PDF_URL = "https://www.stradeanas.it/it/anas_ordinanzeweb/getordinanzapdf?ord_id={id}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m collaudo.italia", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pagine", type=int, default=1)
    ap.add_argument("--delay", type=float, default=15.0)
    args = ap.parse_args(argv)

    out = Path(__file__).parent / "risultati"
    out.mkdir(parents=True, exist_ok=True)
    anas = AnasClient(PDF_URL, os.environ.get("ANAS_USER_AGENT", "WazeItaliaAnasBot"), args.delay)
    listing = ListingClient(anas)
    today = datetime.now(ZoneInfo("Europe/Rome")).date()
    print(f"Ricerca \"tutta Italia\" del {today:%d/%m/%Y}, User-Agent {anas.user_agent}")
    pages = []
    try:
        for page in range(1, args.pagine + 1):
            body = listing.search_page(ITALY, today, page)
            pages.append(body)
            results = body.get("results") or []
            print(f"\nPagina {page}: il sito dichiara tot_record={body.get('tot_record')!r} "
                  f"tot_pagine={body.get('tot_pagine')!r}, risultati ricevuti: {len(results)}")
            if not results:
                print("   NESSUN RISULTATO: chiavi della risposta:", ", ".join(body.keys()))
            for rec in results:
                m = _START.search(re.sub(r"<[^>]+>", " ", rec.get("RIEPILOGO") or "").lower())
                start = f"{m.group(1)}/{m.group(2)}/{m.group(3)}" if m else "-"
                print(f"   ID {rec.get('ID'):>7}  {rec.get('NUMERO_ORDINANZA', ''):<16} "
                      f"{rec.get('COMPARTIMENTO', ''):<28} {rec.get('TIPO_ORDINANZA', ''):<10} inizio {start}")
    except BlockedError as exc:
        print(f"\nQUARANTENA DEL FIREWALL: {exc}. Mi fermo: riprova tra un'ora.")
        return 1
    except (TransientError, ListingError) as exc:
        print(f"\nERRORE: {exc}")
        return 1
    finally:
        if pages:
            (out / "italia.json").write_text(json.dumps(pages, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"\nRisposta grezza salvata in {out / 'italia.json'}")
    ids = [int(r["ID"]) for b in pages for r in (b.get("results") or []) if str(r.get("ID", "")).isdigit()]
    if ids:
        print("Ordine per ID decrescente (= per pubblicazione):", "SI" if ids == sorted(ids, reverse=True) else "NO")
    return 0


if __name__ == "__main__":
    sys.exit(main())
