"""Campionatura: i numeri delle ordinanze ANAS (ord_id) sono progressivi?

    python -m collaudo.campionatura --latest 213695

Controlla:
1. un blocco CONTIGUO degli ultimi N numeri: quanti esistono e quanto è lungo il buco più lungo;
2. finestre più indietro nel tempo (-500, -1000, ... numeri): la numerazione è "piena" anche lì?
3. oltre l'ultimo: deve essere tutto vuoto;
4. l'ordine: a numero (ord_id) più alto corrisponde un'ordinanza più recente?
   Lo verifica con la data dell'atto e con il numero di protocollo della stessa struttura
   (es. 720/2026/BA deve venire prima di 723/2026/BA).

Scrive in campionatura/: campioni.csv (un rigo per numero) e riepilogo.txt (il verdetto).
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from datetime import date
from pathlib import Path

from anas_bot.anas.client import AnasClient, TransientError
from anas_bot.anas.parser import _NUMBER, parse_ordinanza
from anas_bot.anas.pdftext import pdf_to_text
from anas_bot.geo import norm

DEFAULT_URL = "https://www.stradeanas.it/it/anas_ordinanzeweb/getordinanzapdf?ord_id={id}"
_DATE = re.compile(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](20\d{2})\b")


def act_date(text: str) -> str:
    """Data dell'atto: la prima data nell'intestazione (es. 'Ordinanza n. 723/2026 del 28/10/2026')."""
    head = norm(text)[:3000]
    m = re.search(r"\bdel\s+(\d{1,2})[/.\-](\d{1,2})[/.\-](20\d{2})", head) or _DATE.search(head)
    if not m:
        return ""
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
    except ValueError:
        return ""


def longest_run(flags: list[bool]) -> int:
    best = cur = 0
    for f in flags:
        cur = 0 if f else cur + 1
        best = max(best, cur)
    return best


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m collaudo.campionatura", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--latest", type=int, required=True, help="ultimo ord_id esistente (da find-latest)")
    ap.add_argument("--contiguous", type=int, default=200, help="numeri consecutivi da controllare prima dell'ultimo")
    ap.add_argument("--windows", default="500,1000,2000,5000,10000,20000", help="distanze delle finestre all'indietro")
    ap.add_argument("--window-size", type=int, default=20)
    ap.add_argument("--after", type=int, default=30, help="numeri da controllare oltre l'ultimo")
    ap.add_argument("--delay", type=float, default=1.0)
    ap.add_argument("--out", default="campionatura")
    args = ap.parse_args(argv)

    client = AnasClient(os.environ.get("ANAS_PDF_URL", DEFAULT_URL),
                        os.environ.get("ANAS_USER_AGENT", "WazeItaliaAnasBot/1.0 (campionatura)"),
                        delay_seconds=args.delay)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    blocks: list[tuple[str, range]] = [("ultimi", range(args.latest - args.contiguous + 1, args.latest + 1))]
    for d in (int(x) for x in args.windows.split(",") if x.strip()):
        start = args.latest - d
        blocks.append((f"-{d}", range(start, start + args.window_size)))
    blocks.append(("oltre", range(args.latest + 1, args.latest + 1 + args.after)))

    rows: list[dict] = []
    total = sum(len(r) for _, r in blocks)
    done = 0
    for label, ids in blocks:
        for ord_id in ids:
            done += 1
            try:
                data = client.fetch_pdf(ord_id)
            except TransientError as exc:
                print(f"ERRORE dal sito su {ord_id}: {exc} -> mi fermo qui")
                total = done
                break
            row = {"blocco": label, "ord_id": ord_id, "esiste": data is not None,
                   "numero": "", "struttura": "", "data_atto": "", "categoria": ""}
            if data is not None:
                text = pdf_to_text(data)
                o = parse_ordinanza(ord_id, text)
                m = _NUMBER.search(norm(text)[:3000])
                row.update(numero=o.number or (f"{m.group(1)}/{m.group(2)}" if m else ""),
                           struttura=o.structure, data_atto=act_date(text), categoria=o.category)
            rows.append(row)
            if done % 10 == 0:
                print(f"  {done}/{total} numeri controllati...")
        else:
            continue
        break

    with open(out / "campioni.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["ord_id"], delimiter=";")
        w.writeheader()
        w.writerows(rows)

    report = summarize(rows)
    (out / "riepilogo.txt").write_text(report, encoding="utf-8")
    print("\n" + report)
    return 0


def summarize(rows: list[dict]) -> str:
    lines = ["CAMPIONATURA NUMERI ORDINANZE ANAS", ""]
    by_block: dict[str, list[dict]] = {}
    for r in rows:
        by_block.setdefault(r["blocco"], []).append(r)
    for label, rs in by_block.items():
        flags = [r["esiste"] for r in rs]
        found = sum(flags)
        lines.append(f"Blocco {label:>7}: {found}/{len(rs)} esistono ({100 * found // max(1, len(rs))}%), "
                     f"buco più lungo: {longest_run(flags)} numeri")

    found = sorted((r for r in rows if r["esiste"]), key=lambda r: r["ord_id"])
    dated = [r for r in found if r["data_atto"]]
    inversions = sum(1 for a, b in zip(dated, dated[1:]) if b["data_atto"] < a["data_atto"])
    big_inv = sum(1 for a, b in zip(dated, dated[1:])
                  if (date.fromisoformat(a["data_atto"]) - date.fromisoformat(b["data_atto"])).days > 7)
    lines += ["", f"Ordine per data dell'atto: {len(dated)} ordinanze datate, "
              f"{inversions} inversioni (di cui {big_inv} oltre 7 giorni)"]

    # stesso suffisso di struttura (es. /BA): il numero di protocollo deve crescere con l'ord_id
    seq_ok = seq_bad = 0
    by_struct: dict[str, list[tuple[int, int]]] = {}
    for r in found:
        m = re.match(r"(\d+)/(\d{4})(?:/([A-Z]+))?", r["numero"] or "")
        if m:
            key = f"{m.group(2)}/{m.group(3) or r['struttura']}"
            by_struct.setdefault(key, []).append((r["ord_id"], int(m.group(1))))
    for seq in by_struct.values():
        for (_, n1), (_, n2) in zip(seq, seq[1:]):
            seq_ok += n2 > n1
            seq_bad += n2 <= n1
    lines.append(f"Numeri di protocollo nella stessa struttura: {seq_ok} in ordine, {seq_bad} fuori ordine")

    # verdetto
    last = by_block.get("ultimi", [])
    dens = sum(r["esiste"] for r in last) / max(1, len(last))
    beyond = sum(r["esiste"] for r in by_block.get("oltre", []))
    progressive = dens >= 0.9 and big_inv <= 1 and seq_bad <= max(1, seq_ok // 10) and beyond == 0
    lines += ["", "VERDETTO: " + (
        "numerazione PROGRESSIVA e piena: il canale a numeri è affidabile." if progressive else
        "numerazione NON del tutto regolare: serve il controllo sull'elenco ufficiale (vedi i dettagli sopra).")]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
