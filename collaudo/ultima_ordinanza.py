"""Collaudo della parte ANAS, da lanciare sul TUO computer (non serve Slack).

Esempi:
    # scarica 20 ordinanze a partire da un id che sai esistere, le classifica e salva tutto in probe_out/
    python -m collaudo.ultima_ordinanza around 213467 --after 20

    # trova l'ord_id più recente partendo da uno vecchio che sai esistere
    python -m collaudo.ultima_ordinanza find-latest --from 213467

    # classifica PDF o file di testo già scaricati
    python -m collaudo.ultima_ordinanza classify probe_out/*.pdf

Nella cartella di uscita trovi per ogni ordinanza: il PDF, il testo estratto
(.txt) e il risultato della classificazione (.json), più un riepilogo.csv.
Se una classificazione è sbagliata, quei file servono per correggere le
parole chiave in anas_bot/anas/parser.py.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

from anas_bot.anas.client import AnasClient, TransientError
from anas_bot.anas.parser import parse_ordinanza
from anas_bot.anas.pdftext import pdf_to_text

DEFAULT_URL = "https://www.stradeanas.it/it/anas_ordinanzeweb/getordinanzapdf?ord_id={id}"


def _client(args) -> AnasClient:
    return AnasClient(os.environ.get("ANAS_PDF_URL", DEFAULT_URL),
                      os.environ.get("ANAS_USER_AGENT", "WazeItaliaAnasBot"),
                      delay_seconds=args.delay)


def _row(o) -> list:
    return [o.ord_id, o.category, o.number, " ".join(o.roads), o.km_from, o.km_to,
            " ".join(o.provinces), " ".join(o.regions), o.start_date, o.end_date, o.time_window,
            o.speed_kmh or "", "si" if o.extension else "", o.excerpt[:120]]


HEADER = ["ord_id", "categoria", "numero", "strade", "km_da", "km_a", "province", "regioni",
          "inizio", "fine", "orario", "kmh", "proroga", "estratto"]


def cmd_around(args) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    c = _client(args)
    rows = []
    found = 0
    for ord_id in range(args.id - args.before, args.id + args.after + 1):
        try:
            data = c.fetch_pdf(ord_id)
        except TransientError as exc:
            print(f"{ord_id}: ERRORE TEMPORANEO {exc} -> mi fermo")
            break
        if data is None:
            print(f"{ord_id}: non esiste")
            rows.append([ord_id, "NON TROVATA"] + [""] * (len(HEADER) - 2))
            continue
        found += 1
        text = pdf_to_text(data)
        o = parse_ordinanza(ord_id, text, c.url_for(ord_id))
        (out / f"{ord_id}.pdf").write_bytes(data)
        (out / f"{ord_id}.txt").write_text(text, encoding="utf-8")
        (out / f"{ord_id}.json").write_text(json.dumps(o.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        rows.append(_row(o))
        print(f"{ord_id}: {o.category:16} {' '.join(o.roads)[:30]:30} {' '.join(o.provinces):12} "
              f"{o.start_date}→{o.end_date}")
    with open(out / "riepilogo.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(HEADER)
        w.writerows(rows)
    print(f"\n{found} ordinanze trovate. Risultati in {out.resolve()}")
    return 0


def _exists(c: AnasClient, ord_id: int, window: int) -> int | None:
    """Primo id esistente in [ord_id, ord_id+window), tollera i buchi nella numerazione."""
    for i in range(ord_id, ord_id + window):
        if c.fetch_pdf(i) is not None:
            return i
    return None


def cmd_find_latest(args) -> int:
    c = _client(args)
    try:
        return _find_latest(c, args)
    except TransientError as exc:
        print(f"ERRORE dal sito ANAS: {exc}")
        print(f"Per capire cosa risponde: python -m collaudo.ultima_ordinanza check {args.from_id}")
        return 1


def _find_latest(c: AnasClient, args) -> int:
    lo = _exists(c, args.from_id, args.window)
    if lo is None:
        print(f"Nessuna ordinanza tra {args.from_id} e {args.from_id + args.window}: prova con un altro id.")
        return 1
    step = 256
    while True:  # salti in avanti sempre più lunghi finché non troviamo il vuoto
        hit = _exists(c, lo + step, args.window)
        print(f"  provo {lo + step}: {'esiste' if hit else 'vuoto'}")
        if hit is None:
            break
        lo, step = hit, step * 2
    hi = lo + step
    while hi - lo > args.window:  # ricerca binaria nell'intervallo
        mid = (lo + hi) // 2
        hit = _exists(c, mid, args.window)
        print(f"  provo {mid}: {'esiste' if hit else 'vuoto'}")
        if hit is None:
            hi = mid
        else:
            lo = hit
    for i in range(lo + 1, hi + 1):  # rifinitura
        if c.fetch_pdf(i) is not None:
            lo = i
    print(f"\nUltimo ord_id trovato: {lo}  -> metti ANAS_START_ID={lo} nel file .env")
    return 0


def cmd_check(args) -> int:
    """Diagnosi: mostra cosa risponde davvero il sito per un ord_id (stato, redirect, tipo, inizio del contenuto)."""
    import requests

    c = _client(args)
    url = c.url_for(args.id)
    print(f"URL richiesto: {url}")
    print(f"User-Agent:    {c.session.headers['User-Agent']}")
    try:
        r = c.session.get(url, timeout=(10, 60), allow_redirects=True)
    except requests.RequestException as exc:
        print(f"ERRORE DI RETE: {exc}")
        return 1
    for h in r.history:
        print(f"Redirect:      HTTP {h.status_code} -> {h.headers.get('Location')}")
    print(f"Stato finale:  HTTP {r.status_code}")
    print(f"URL finale:    {r.url}")
    print(f"Content-Type:  {r.headers.get('Content-Type')}")
    print(f"Dimensione:    {len(r.content)} byte")
    print(f"Cookie:        {', '.join(r.cookies.keys()) or 'nessuno'}")
    body = r.content
    if body[:5] == b"%PDF-":
        print("Contenuto:     PDF valido")
    else:
        print("Contenuto (primi 1500 caratteri):")
        print(body[:1500].decode("utf-8", "replace"))
    return 0


def cmd_classify(args) -> int:
    for path in args.files:
        p = Path(path)
        text = pdf_to_text(p.read_bytes()) if p.suffix.lower() == ".pdf" else p.read_text(encoding="utf-8")
        try:
            ord_id = int(p.stem)
        except ValueError:
            ord_id = 0
        o = parse_ordinanza(ord_id, text)
        print(f"--- {p.name}")
        print(json.dumps(o.to_dict(), ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m collaudo.ultima_ordinanza", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--delay", type=float, default=2.0, help="secondi tra una richiesta e l'altra (default 2)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("around", help="scarica e classifica ordinanze attorno a un id")
    a.add_argument("id", type=int)
    a.add_argument("--before", type=int, default=0)
    a.add_argument("--after", type=int, default=20)
    a.add_argument("--out", default="probe_out")
    a.set_defaults(func=cmd_around)

    f = sub.add_parser("find-latest", help="trova l'ord_id più recente")
    f.add_argument("--from", dest="from_id", type=int, required=True)
    f.add_argument("--window", type=int, default=15, help="buchi tollerati nella numerazione")
    f.set_defaults(func=cmd_find_latest)

    ch = sub.add_parser("check", help="diagnosi: cosa risponde il sito per un id")
    ch.add_argument("id", type=int)
    ch.set_defaults(func=cmd_check)

    k = sub.add_parser("classify", help="classifica PDF o .txt locali")
    k.add_argument("files", nargs="+")
    k.set_defaults(func=cmd_classify)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
