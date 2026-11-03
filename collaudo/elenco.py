"""Collaudo completo sull'elenco ufficiale: TUTTE le ordinanze in vigore, in tutta Italia.

    python -m collaudo.elenco --out elenco

Due fasi:
1. SCARICAMENTO (lungo, riprendibile): trova le strutture territoriali e scarica tutte le
   pagine dell'elenco. Ogni struttura completata viene salvata subito in elenco/grezzi/:
   se chiudi la finestra, rilanciando riparte da dove si era fermato.
2. ANALISI (pochi secondi): dai dati scaricati scrive in elenco/
   - strutture.csv      sigle e nomi (es. BA = Bari) e quante ordinanze ha ciascuna
   - ordinanze.csv      ogni ordinanza con la classificazione del bot
   - provvedimenti.csv  il VOCABOLARIO: ogni voce di provvedimento, quante volte compare, esempi
   - corsie.csv         le diciture su corsie/rampe/carreggiate, con esempi
   - tipi_cause.csv     tipi di ordinanza, cause, dettagli causa, utenti interessati
   - riepilogo.txt      i numeri principali e le chiusure trovate
   - pagina.html        la pagina di Ordinanze Web, per diagnosi
Non scarica PDF: solo l'elenco (una richiesta ogni 5 ordinanze).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from anas_bot.anas.client import AnasClient, TransientError
from anas_bot.anas.listing import MAX_RESULTS, ListingClient, ListingError, Structure, record_to_ordinanza, split_provisions
from anas_bot.anas.vocabolario import KNOWN_MEASURES, measure_key

PDF_URL = "https://www.stradeanas.it/it/anas_ordinanzeweb/getordinanzapdf?ord_id={id}"
RETRIES = 3  # nuovi tentativi se il sito non risponde (con attese di 30, 60, 90 secondi)


# --- Avanzamento ------------------------------------------------------------------

class Progress:
    """Stampa ogni passo con orario, richieste fatte e tempo stimato alla fine."""

    def __init__(self) -> None:
        self.started = time.monotonic()
        self.requests = 0
        self.request_time = 0.0
        self._last = time.monotonic()

    def tick(self) -> None:
        now = time.monotonic()
        self.requests += 1
        self.request_time += now - self._last
        self._last = now

    def avg(self) -> float:
        return self.request_time / self.requests if self.requests else 4.0

    def eta(self, remaining_requests: int) -> str:
        sec = int(remaining_requests * self.avg())
        return f"{sec // 60} min {sec % 60:02d} s" if sec >= 60 else f"{sec} s"

    def say(self, msg: str) -> None:
        elapsed = int(time.monotonic() - self.started)
        print(f"[{datetime.now():%H:%M:%S} | {elapsed // 60:>3}:{elapsed % 60:02d}] {msg}", flush=True)


# --- Fase 1: scaricamento riprendibile --------------------------------------------

def download(listing: ListingClient, out: Path, only: set[str], pr: Progress) -> tuple[list[Structure], int, list[str]]:
    today = datetime.now(ZoneInfo("Europe/Rome")).date()
    raw_dir = out / "grezzi"
    raw_dir.mkdir(parents=True, exist_ok=True)
    cache = out / "strutture.json"

    def on_retry(attempt, maximum, wait, exc):
        pr.say(f"   ⚠ il sito non risponde ({exc}). Riprovo tra {wait} s (tentativo {attempt}/{maximum})...")
    listing.on_retry = on_retry

    # strutture: dalla cache se c'è (ripresa), altrimenti dal menu o scoprendo le sigle
    if cache.exists():
        saved = json.loads(cache.read_text(encoding="utf-8"))
        structures = [Structure(**s) for s in saved["strutture"]]
        total_italy = saved.get("totale_italia", -1)
        pr.say(f"Riprendo il lavoro: {len(structures)} strutture già individuate (salvate il {saved['data']}).")
    else:
        pr.say("FASE 1/3 - Cerco le strutture territoriali...")
        page = listing.prime()
        (out / "pagina.html").write_text(page, encoding="utf-8")
        pr.tick()
        from anas_bot.anas.listing import CANDIDATE_CODES, parse_structures
        structures = parse_structures(page)
        if structures:
            pr.say(f"   Trovate nel menu della pagina: {len(structures)} strutture.")
        else:
            pr.say(f"   Il menu non è nella pagina: provo le {len(CANDIDATE_CODES)} sigle possibili, una per una.")

            def found_cb(i, n, code, st, total):
                pr.tick()
                esito = f"TROVATA: {st.label}, {total} ordinanze" if st else "nessun risultato"
                pr.say(f"   sigla {i:>2}/{n} {code:<3} -> {esito}   (fine stimata tra {pr.eta(n - i)})")
            structures = listing.discover_structures(today, progress=found_cb, retries=RETRIES)
        total_italy = listing._with_retries(lambda: listing.total_italy(today), RETRIES)
        pr.tick()
        cache.write_text(json.dumps({"data": today.isoformat(), "totale_italia": total_italy,
                                     "strutture": [s.__dict__ for s in structures]}, ensure_ascii=False),
                         encoding="utf-8")
        pr.say(f"   Strutture: {', '.join(f'{s.code}={s.label}' for s in structures)}")
        pr.say(f"   Ordinanze in vigore in tutta Italia secondo il sito: {total_italy}")

    if only:
        structures = [s for s in structures if s.code.upper() in only]

    pr.say("FASE 2/3 - Scarico l'elenco di ogni struttura (5 ordinanze per pagina).")
    errors = []
    todo = [s for s in structures if not (raw_dir / f"{s.code}.jsonl").exists()]
    done_before = len(structures) - len(todo)
    if done_before:
        pr.say(f"   {done_before} strutture già scaricate in precedenza: le salto.")
    pages_left = {"n": 30 * len(todo)}  # stima iniziale, poi si aggiorna con i totali veri
    for k, st in enumerate(todo, 1):
        tmp = raw_dir / f"{st.code}.jsonl.tmp"
        state = {"pages": 0}

        def on_page(page, pages, total, st=st, k=k, state=state):
            pr.tick()
            if page == 1:
                pages_left["n"] += pages - 30
            pages_left["n"] -= 1
            state["pages"] = pages
            pr.say(f"   [{done_before + k}/{len(structures)}] {st.code} {st.label}: pagina {page}/{pages} "
                   f"({total} ordinanze)   fine stimata tra {pr.eta(max(0, pages_left['n']))}")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                for rec in listing.iter_structure(st.code, today, on_page=on_page, retries=RETRIES):
                    f.write(json.dumps({"struttura": st.code, "struttura_nome": st.label, **rec},
                                       ensure_ascii=False) + "\n")
            tmp.replace(raw_dir / f"{st.code}.jsonl")  # completata: salvata in modo definitivo
            if listing.last_total_records >= MAX_RESULTS:
                pr.say(f"   ⚠ {st.code} ha almeno {MAX_RESULTS} ordinanze: il sito ne mostra solo {MAX_RESULTS}!")
        except (TransientError, ListingError) as exc:
            errors.append(f"{st.code}: {exc}")
            pr.say(f"   ✖ {st.code} {st.label}: BLOCCATO dopo {RETRIES} tentativi ({exc}). Passo alla successiva.")
            pr.say("     Rilanciando elenco.bat più tardi verrà ripresa da qui.")
    return structures, total_italy, errors


# --- Fase 2: analisi -------------------------------------------------------------

def analyze(out: Path, structures: list[Structure], total_italy: int, errors: list[str]) -> str:
    measures: dict[str, list] = defaultdict(lambda: [0, set(), Counter()])  # conteggio, esempi, categorie
    lanes: dict[str, list] = defaultdict(lambda: [0, set()])
    meta = Counter()
    per_struct = []
    rows = []
    for st in structures:
        path = out / "grezzi" / f"{st.code}.jsonl"
        if not path.exists():
            per_struct.append((st.code, st.label, 0, "non scaricata"))
            continue
        recs = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        per_struct.append((st.code, st.label, len(recs), len(recs)))
        for rec in recs:
            o = record_to_ordinanza(rec, st.label, PDF_URL.format(id=rec.get("ID")))
            cat = o.category if o else "serve PDF"
            for key in ("TIPO_ORDINANZA", "CAUSA", "CAUSA_DETT"):
                meta[(key, rec.get(key, ""))] += 1
            for p in split_provisions(rec.get("RIEPILOGO", "")):
                for m in p.measures:
                    e = measures[measure_key(m)]
                    e[0] += 1
                    e[2][cat] += 1
                    if len(e[1]) < 3:
                        e[1].add(rec.get("ID"))
                lane = re.sub(r"\d+\+\d+", "N+N", p.lanes.split(" km ")[-1] if " km " in p.lanes else p.lanes)[:150]
                le = lanes[lane.strip()]
                le[0] += 1
                if len(le[1]) < 3:
                    le[1].add(rec.get("ID"))
                if "interessera:" in p.text:
                    meta[("INTERESSERA", p.text.split("interessera:")[-1].strip()[:80])] += 1
            rows.append({
                "struttura": st.code, "id": rec.get("ID"), "numero": rec.get("NUMERO_ORDINANZA"),
                "tipo": rec.get("TIPO_ORDINANZA"), "causa": rec.get("CAUSA"), "categoria": cat,
                "rampa": "si" if o and o.ramp_only else "", "proroga": "si" if o and o.extension else "",
                "strade": " ".join(o.roads) if o else "", "km": f"{o.km_from} {o.km_to}".strip() if o else "",
                "inizio": o.start_date if o else "", "fine": o.end_date if o else "",
                "orario": o.time_window if o else "", "kmh": (o.speed_kmh or "") if o else "",
                "riepilogo": (o.excerpt if o else "")[:300],
            })

    def write(name, header, data):
        with open(out / name, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(header)
            w.writerows(data)

    write("strutture.csv", ["sigla", "nome", "ordinanze", "note"], per_struct)
    with open(out / "ordinanze.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["id"], delimiter=";")
        w.writeheader()
        w.writerows(rows)
    write("provvedimenti.csv", ["provvedimento", "volte", "classificate_come", "esempi_id", "nuova"],
          [[k, c, " ".join(f"{a}:{b}" for a, b in cats.most_common()), " ".join(sorted(ex)),
            "" if k in KNOWN_MEASURES else "NUOVA"]
           for k, (c, ex, cats) in sorted(measures.items(), key=lambda kv: -kv[1][0])])
    write("corsie.csv", ["dicitura", "volte", "esempi_id"],
          [[k, c, " ".join(sorted(ex))] for k, (c, ex) in sorted(lanes.items(), key=lambda kv: -kv[1][0])])
    write("tipi_cause.csv", ["campo", "valore", "volte"],
          [[k, v, c] for (k, v), c in sorted(meta.items(), key=lambda kv: (kv[0][0], -kv[1]))])

    cats = Counter(r["categoria"] for r in rows)
    new_measures = [k for k in measures if k not in KNOWN_MEASURES]
    missing = [c for c, _, _, note in per_struct if note == "non scaricata"]
    lines = [f"COLLAUDO ELENCO UFFICIALE ANAS - {datetime.now():%Y-%m-%d %H:%M}", "",
             f"Strutture: {len(per_struct)} (scaricate {len(per_struct) - len(missing)})   "
             f"Ordinanze lette: {len(rows)}",
             f"Voci di provvedimento diverse: {len(measures)} (nuove rispetto al vocabolario: {len(new_measures)})",
             *[f"  NUOVA: {k}" for k in new_measures], "",
             "Classificazione del bot:"] + [f"  {k:<16} {v}" for k, v in cats.most_common()]
    lines += ["", f"Controllo completezza: tutta Italia secondo il sito = {total_italy}, lette = {len(rows)}"
              + ("  (OK)" if total_italy == len(rows) else "  (DIVERSI)")]
    if missing:
        lines += [f"NON ancora scaricate: {', '.join(missing)} (rilancia elenco.bat per completarle)"]
    if errors:
        lines += ["", "Errori:"] + [f"  {e}" for e in errors]
    lines += ["", "Chiusure trovate (da verificare a campione):"]
    lines += [f"  {r['id']} {r['numero']} {r['strade']} km {r['km']} {'RAMPA' if r['rampa'] else ''}"
              for r in rows if r["categoria"] == "chiusura"][:80]
    report = "\n".join(lines) + "\n"
    (out / "riepilogo.txt").write_text(report, encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m collaudo.elenco", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="elenco")
    ap.add_argument("--delay", type=float, default=1.0)
    ap.add_argument("--only", default="", help="solo queste strutture, es. BA,MI (per una prova veloce)")
    ap.add_argument("--restart", action="store_true", help="ricomincia da zero invece di riprendere")
    args = ap.parse_args(argv)

    out = Path(args.out)
    if args.restart and out.exists():
        for f in list((out / "grezzi").glob("*")) + [out / "strutture.json"]:
            if f.exists():
                f.unlink()
    out.mkdir(parents=True, exist_ok=True)
    anas = AnasClient(os.environ.get("ANAS_PDF_URL", PDF_URL),
                      os.environ.get("ANAS_USER_AGENT", "WazeItaliaAnasBot/1.0 (collaudo elenco)"), args.delay)
    listing = ListingClient(anas)
    pr = Progress()
    pr.say("Avvio. Ogni riga con l'orario indica che il lavoro sta andando avanti.")
    pr.say("Puoi chiudere la finestra quando vuoi: rilanciando, riprende da dove era rimasto.")
    try:
        structures, total_italy, errors = download(listing, out, {c.strip().upper() for c in args.only.split(",")
                                                                  if c.strip()}, pr)
    except (TransientError, ListingError) as exc:
        pr.say(f"✖ BLOCCATO: {exc}")
        pr.say("Il sito non risponde o ha cambiato formato. Rilancia più tardi; se si ripete, manda elenco.log in chat.")
        return 1
    pr.say("FASE 3/3 - Analizzo i dati scaricati...")
    report = analyze(out, structures, total_italy, errors)
    print("\n" + report)
    return 0 if not errors else 3


if __name__ == "__main__":
    sys.exit(main())
