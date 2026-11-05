"""Atlante imparato: strada + chilometri -> province, dai PDF già letti.

L'elenco di ANAS non dice la provincia: la dicono i destinatari in testa al PDF (prefetture, comuni),
che il bot legge soprattutto di notte. Ogni volta che un PDF rivela la provincia di un tratto, il bot
se lo segna qui (tabella `atlante` in D1); dalla volta dopo un'ordinanza sullo stesso tratto ha la
provincia senza scaricare niente ("provincia dedotta dall'atlante"). Con i giorni i PDF servono
sempre meno.

Un tratto è (strada, km da, km a). Una richiesta trova le voci della stessa strada il cui intervallo
di chilometri si sovrappone a quello cercato; se non ha chilometri, vale l'intera strada solo quando
tutte le voci concordano su una provincia sola (strade corte, es. raccordi).
"""

from __future__ import annotations

import json
import logging
import re

log = logging.getLogger(__name__)

_KM = re.compile(r"(\d+)(?:\+(\d+))?")


def km_to_m(km: str) -> int | None:
    """"12+500" -> 12500; "" o non numerico -> None."""
    m = _KM.match((km or "").strip())
    if not m:
        return None
    return int(m.group(1)) * 1000 + int(m.group(2) or 0)


class Atlante:
    def __init__(self, backend) -> None:
        self.b = backend

    def learn(self, roads: list[str], km_from: str, km_to: str, provinces: list[str], ord_id: int) -> None:
        """Segna che il tratto (strada, km) sta in queste province (sorgente: il PDF dell'ordinanza)."""
        if not roads or not provinces:
            return
        a, b = km_to_m(km_from), km_to_m(km_to)
        if a is not None and b is not None and a > b:
            a, b = b, a
        for road in roads:
            self.b.query(
                "INSERT OR REPLACE INTO atlante(road, km_from, km_to, provinces, ord_id) VALUES(?,?,?,?,?)",
                (road, a if a is not None else -1, b if b is not None else -1,
                 json.dumps(sorted(provinces)), ord_id))

    def seed_from_archive(self, db) -> int:
        """Una volta sola: travasa nell'atlante le ordinanze già in archivio che hanno strada, chilometri e
        province lette dal PDF (le notti scorse). Zero richieste ad ANAS. Restituisce quante voci ha aggiunto."""
        if db.get("atlante_seeded") == "1":
            return 0
        n = 0
        stmts = []
        for o in db.all_ordinanze_with_provinces():
            if o.roads and o.provinces and (o.km_from or o.km_to):
                a, b = km_to_m(o.km_from), km_to_m(o.km_to)
                if a is not None and b is not None and a > b:
                    a, b = b, a
                for road in o.roads:
                    stmts.append(("INSERT OR REPLACE INTO atlante(road, km_from, km_to, provinces, ord_id) VALUES(?,?,?,?,?)",
                                  (road, a if a is not None else -1, b if b is not None else -1,
                                   json.dumps(sorted(o.provinces)), o.ord_id)))
                n += 1
        for i in range(0, len(stmts), 200):  # a blocchi: una chiamata a D1 per 200 voci
            self.b.batch(stmts[i:i + 200])
        db.set("atlante_seeded", "1")
        log.info("Atlante: %d tratti imparati dall'archivio", n)
        return n

    def lookup(self, roads: list[str], km_from: str, km_to: str) -> list[str]:
        """Province dedotte per il tratto; [] se l'atlante non sa."""
        a, b = km_to_m(km_from), km_to_m(km_to)
        if a is not None and b is not None and a > b:
            a, b = b, a
        found: set[str] = set()
        for road in roads:
            rows = self.b.query("SELECT km_from, km_to, provinces FROM atlante WHERE road=?", (road,))
            if not rows:
                continue
            if a is None:
                # senza chilometri: solo se tutta la strada conosciuta sta in una provincia sola
                all_provs = {p for r in rows for p in json.loads(r["provinces"])}
                if len(all_provs) == 1:
                    found |= all_provs
                continue
            b2 = b if b is not None else a
            for r in rows:
                ra, rb = int(r["km_from"]), int(r["km_to"])
                if ra < 0:
                    continue  # voce senza chilometri: non si estende a un tratto preciso
                if ra <= b2 and rb >= a:  # intervalli che si sovrappongono
                    found |= set(json.loads(r["provinces"]))
        return sorted(found)
