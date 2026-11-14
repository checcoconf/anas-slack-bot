"""Database: lo stato condiviso tra il Cloudflare Worker e il job di GitHub Actions.

In produzione è Cloudflare D1, raggiunto via API REST. Nei test e nelle prove
sul PC è un file SQLite locale. Lo schema è lo stesso (schema.sql) e le query
anche: cambia solo il "trasporto" (backend).

Tabelle:
- kv:          cursore ANAS e altri valori singoli;
- missing_ids: buchi nella numerazione da ricontrollare;
- ordinanze:   ogni ordinanza scaricata, classificata, con stato di notifica;
- users:       iscritti e preferenze (le scrive il Worker quando si salva il modulo);
- deliveries:  coda dei messaggi da mandare.

Nota sulla robustezza: ogni operazione multipla è scritta in modo che, se si
interrompe a metà, rieseguirla non faccia danni (INSERT OR IGNORE, aggiornamenti
"assoluti" e lo stato finale scritto per ultimo). Così non serve fidarsi delle
transazioni via API REST.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .anas.parser import Ordinanza

log = logging.getLogger(__name__)

SCHEMA = (Path(__file__).with_name("schema.sql")).read_text(encoding="utf-8")


# Colonne aggiunte dopo la prima versione: (tabella, colonna, definizione). Il job le aggiunge da solo
# se mancano (migrate); il workflow del Worker fa lo stesso con "ALTER TABLE ... || true".
MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    ("users", "want_all", "INTEGER NOT NULL DEFAULT 0"),
    ("users", "all_regions", "TEXT NOT NULL DEFAULT '[]'"),
    ("users", "all_provinces", "TEXT NOT NULL DEFAULT '[]'"),
)


def migrate(backend: "Backend") -> list[str]:
    """Aggiunge le colonne mancanti; restituisce i nomi di quelle aggiunte.

    Non deve mai fermare il job: se PRAGMA non è disponibile si prova l'ALTER alla cieca, e un
    "duplicate column" (colonna già presente) è la risposta normale."""
    added = []
    for table, column, definition in MIGRATIONS:
        try:
            present = {r.get("name") for r in backend.query(f"PRAGMA table_info({table})")}
        except Exception as exc:  # noqa: BLE001 - backend senza PRAGMA: si tenta l'ALTER direttamente
            log.info("PRAGMA table_info non disponibile (%s): provo l'ALTER direttamente", exc)
            present = None
        if present is not None and column in present:
            continue
        try:
            backend.query(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            added.append(f"{table}.{column}")
        except Exception as exc:  # noqa: BLE001
            if "duplicate column" not in str(exc).lower():
                log.warning("Migrazione %s.%s non riuscita (%s): il job continua con lo schema attuale", table, column, exc)
    return added


def schema_statements() -> list[str]:
    """Le istruzioni di schema.sql una per una (tutte "IF NOT EXISTS": si possono ripetere)."""
    sql = "\n".join(line for line in SCHEMA.splitlines() if not line.lstrip().startswith("--"))
    return [st.strip() for st in sql.split(";") if st.strip()]


MAX_STORED_TEXT = 20_000  # caratteri di testo PDF conservati per rianalisi
# Cloudflare D1 accetta al massimo 100 valori "?" per query (14/11/2026: "too many SQL variables" con ~120 avvisi
# di Bolzano in un IN (...)); in locale il limite è molto più alto, quindi lo si rispetta sempre.
MAX_SQL_VARS = 90

Stmt = tuple[str, tuple[Any, ...]]


class Backend(Protocol):
    def query(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict]: ...
    def batch(self, stmts: list[Stmt]) -> None: ...


class LocalSqlite:
    """SQLite su file: per i test e per provare il job sul PC senza Cloudflare."""

    def __init__(self, path: str) -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            if path != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(SCHEMA)

    def query(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def batch(self, stmts: list[Stmt]) -> None:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                for sql, params in stmts:
                    self._conn.execute(sql, params)
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")


class D1Error(RuntimeError):
    pass


class D1Http:
    """Cloudflare D1 via API REST (POST /accounts/{id}/d1/database/{id}/query)."""

    def __init__(self, account_id: str, database_id: str, api_token: str, timeout: float = 30) -> None:
        self.url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/d1/database/{database_id}/query"
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"})
        retry = Retry(total=4, backoff_factor=1.5, status_forcelist=(429, 500, 502, 503, 504),
                      allowed_methods=frozenset({"POST"}), respect_retry_after_header=True)
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    @staticmethod
    def _param(v: Any) -> Any:
        if v is None:
            return None
        if isinstance(v, bool):
            return int(v)
        return v

    def _post(self, body: dict) -> list[dict]:
        r = self.session.post(self.url, json=body, timeout=self.timeout)
        try:
            data = r.json()
        except ValueError as exc:
            raise D1Error(f"D1 HTTP {r.status_code}: risposta non JSON") from exc
        if not data.get("success"):
            msgs = "; ".join(e.get("message", "") for e in data.get("errors", []))
            raise D1Error(f"D1 HTTP {r.status_code}: {msgs or 'errore sconosciuto'}")
        return data.get("result", [])

    def query(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict]:
        result = self._post({"sql": sql, "params": [self._param(p) for p in params]})
        return result[0].get("results", []) if result else []

    def batch(self, stmts: list[Stmt]) -> None:
        if not stmts:
            return
        self._post({"batch": [{"sql": s, "params": [self._param(p) for p in ps]} for s, ps in stmts]})


@dataclass
class User:
    user_id: str
    in_channel: bool = True
    paused: bool = False
    configured: bool = False
    all_italy: bool = False
    regions: list[str] = field(default_factory=list)
    provinces: list[str] = field(default_factory=list)
    want_closures: bool = True
    want_speed: bool = True
    want_all: bool = False  # anche cantieri, restringimenti, sensi unici...: tutte le altre ordinanze
    all_regions: list[str] = field(default_factory=list)    # zone dei cantieri; vuote = le stesse zone
    all_provinces: list[str] = field(default_factory=list)
    welcomed_at: float | None = None

    @property
    def receives(self) -> bool:
        return self.in_channel and not self.paused and self.configured


def _row_to_user(r: dict) -> User:
    return User(
        user_id=r["user_id"],
        in_channel=bool(r["in_channel"]),
        paused=bool(r["paused"]),
        configured=bool(r["configured"]),
        all_italy=bool(r["all_italy"]),
        regions=json.loads(r["regions"] or "[]"),
        provinces=json.loads(r["provinces"] or "[]"),
        want_closures=bool(r["want_closures"]),
        want_speed=bool(r["want_speed"]),
        want_all=bool(r.get("want_all") or 0),
        all_regions=json.loads(r.get("all_regions") or "[]"),
        all_provinces=json.loads(r.get("all_provinces") or "[]"),
        welcomed_at=r["welcomed_at"],
    )


def ordinanza_from_json(data: str) -> Ordinanza:
    d = json.loads(data)
    known = set(Ordinanza.__dataclass_fields__)
    return Ordinanza(**{k: v for k, v in d.items() if k in known})


RELEVANT = ("chiusura", "riapertura", "limite_velocita")
UNREAD = 0  # parser_version delle ordinanze segnate come viste senza leggerle (installazione): nessun dettaglio

_UPSERT_USER = "INSERT OR IGNORE INTO users(user_id, updated_at) VALUES(?,?)"


class Database:
    def __init__(self, backend: Backend) -> None:
        self.b = backend

    @classmethod
    def local(cls, path: str) -> "Database":
        return cls(LocalSqlite(path))

    # --- kv -------------------------------------------------------------
    def get(self, key: str, default: str | None = None) -> str | None:
        rows = self.b.query("SELECT value FROM kv WHERE key=?", (key,))
        return rows[0]["value"] if rows else default

    def set(self, key: str, value: str) -> None:
        self.b.query("INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                     (key, value))

    def cursor(self) -> int | None:
        v = self.get("anas_cursor")
        return int(v) if v is not None else None

    # --- id mancanti ----------------------------------------------------
    def add_missing(self, ids: list[int]) -> None:
        now = time.time()
        self.b.batch([("INSERT OR IGNORE INTO missing_ids(ord_id, first_missed_at) VALUES(?,?)", (i, now))
                      for i in ids])

    def missing_to_recheck(self, limit: int, max_age_hours: int) -> list[int]:
        cutoff = time.time() - max_age_hours * 3600
        self.b.query("DELETE FROM missing_ids WHERE first_missed_at < ?", (cutoff,))
        rows = self.b.query("SELECT ord_id FROM missing_ids ORDER BY attempts ASC, ord_id ASC LIMIT ?", (limit,))
        return [int(r["ord_id"]) for r in rows]

    def missing_attempted(self, ord_id: int) -> None:
        self.b.query("UPDATE missing_ids SET attempts = attempts + 1 WHERE ord_id=?", (ord_id,))

    # --- ordinanze ------------------------------------------------------
    def has_ordinanza(self, ord_id: int) -> bool:
        return bool(self.b.query("SELECT 1 AS x FROM ordinanze WHERE ord_id=?", (ord_id,)))

    def save_ordinanza(self, o: Ordinanza, text: str, advance_cursor_to: int | None = None,
                       silent: bool = False) -> None:
        """Salva l'ordinanza, la toglie dai mancanti e (per ultimo) avanza il cursore.

        silent=True: ordinanza già in vigore prima dell'installazione del bot. Viene
        segnata come vista (stato 3) ma non notificata: niente ordinanze vecchie.
        """
        state = 3 if silent else 0  # anche le "altre" passano dalla coda: c'è chi vuole tutto (want_all)
        stmts: list[Stmt] = [
            ("INSERT OR IGNORE INTO ordinanze(ord_id, fetched_at, category, data, text, notify_state) "
             "VALUES(?,?,?,?,?,?)",
             (o.ord_id, time.time(), o.category, json.dumps(o.to_dict(), ensure_ascii=False),
              text[:MAX_STORED_TEXT], state)),
            ("DELETE FROM missing_ids WHERE ord_id=?", (o.ord_id,)),
        ]
        if advance_cursor_to is not None:
            stmts.append((
                "INSERT INTO kv(key,value) VALUES('anas_cursor', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value "
                "WHERE CAST(kv.value AS INTEGER) < CAST(excluded.value AS INTEGER)",
                (str(advance_cursor_to),),
            ))
        self.b.batch(stmts)

    def known_among(self, ids: list[int]) -> set[int]:
        """Quali di questi ord_id sono già nel database (una query ogni MAX_SQL_VARS id)."""
        found: set[int] = set()
        for i in range(0, len(ids), MAX_SQL_VARS):
            chunk = ids[i:i + MAX_SQL_VARS]
            marks = ",".join("?" * len(chunk))
            rows = self.b.query(f"SELECT ord_id FROM ordinanze WHERE ord_id IN ({marks})", tuple(chunk))
            found |= {int(r["ord_id"]) for r in rows}
        return found

    def find_by_number(self, number: str) -> Ordinanza | None:
        """L'ordinanza con questo numero (es. "650/2026/BA"), se il bot l'ha già vista."""
        rows = self.b.query("SELECT data FROM ordinanze WHERE data LIKE ? ORDER BY ord_id DESC LIMIT 1",
                            (f'%"number": "{number}"%',))
        return ordinanza_from_json(rows[0]["data"]) if rows else None

    def upgrade_from_listing(self, o: Ordinanza) -> bool:
        """L'elenco ufficiale dice che un'ordinanza già vista come "altro" è utile: la rimette in coda.

        Vale solo per le ordinanze viste come "altro" (in coda, scartate o già mandate come tali a chi
        vuole tutto), mai per quelle già utili o silenziate all'installazione.
        """
        rows = self.b.query("SELECT notify_state, category FROM ordinanze WHERE ord_id=?", (o.ord_id,))
        if not rows or int(rows[0]["notify_state"]) == 3 or rows[0]["category"] in RELEVANT \
                or o.category not in RELEVANT:
            return False
        self.b.query("UPDATE ordinanze SET category=?, data=?, notify_state=0 WHERE ord_id=?",
                     (o.category, json.dumps(o.to_dict(), ensure_ascii=False), o.ord_id))
        return True

    def known_ids(self, lo: int, hi: int) -> set[int]:
        """ord_id già salvati nell'intervallo [lo, hi] (una sola query, anche su D1)."""
        rows = self.b.query("SELECT ord_id FROM ordinanze WHERE ord_id BETWEEN ? AND ?", (lo, hi))
        return {int(r["ord_id"]) for r in rows}

    def open_ids_in_range(self, lo: int, hi: int, today: date) -> set[int]:
        """ID in [lo, hi) senza fine o con fine da oggi in poi (avvisi delle fonti oltre ANAS ancora attivi)."""
        rows = self.b.query(
            "SELECT ord_id FROM ordinanze WHERE ord_id >= ? AND ord_id < ? AND (json_extract(data, '$.end_date') "
            "IS NULL OR json_extract(data, '$.end_date') = '' OR json_extract(data, '$.end_date') >= ?)",
            (lo, hi, today.isoformat()))
        return {int(r["ord_id"]) for r in rows}

    def end_ordinanze(self, ord_ids: list[int], end: date) -> None:
        """Segna come finiti questi avvisi (spariti dalla fonte): fine = `end`, niente "senza fine"."""
        if ord_ids:
            self.b.batch([("UPDATE ordinanze SET data = json_set(data, '$.end_date', ?, '$.open_ended', json('false')) "
                           "WHERE ord_id = ?", (end.isoformat(), i)) for i in ord_ids])

    def get_ordinanza(self, ord_id: int) -> Ordinanza | None:
        rows = self.b.query("SELECT data FROM ordinanze WHERE ord_id=?", (ord_id,))
        return ordinanza_from_json(rows[0]["data"]) if rows else None

    def get_ordinanze(self, ord_ids: list[int]) -> list[Ordinanza]:
        rows: list[dict] = []
        for i in range(0, len(ord_ids), MAX_SQL_VARS):
            chunk = ord_ids[i:i + MAX_SQL_VARS]
            marks = ",".join("?" * len(chunk))
            rows += self.b.query(f"SELECT data FROM ordinanze WHERE ord_id IN ({marks})", tuple(chunk))
        return sorted((ordinanza_from_json(r["data"]) for r in rows), key=lambda o: o.ord_id)

    def in_force_ordinanze(self, today: date, categories: tuple[str, ...] = RELEVANT) -> list[Ordinanza]:
        """Ordinanze ancora in vigore (per il riepilogo a chi si iscrive), già valutate dalla coda (1, 2) o già
        in vigore all'installazione (3); la scadenza si filtra in SQL per non caricare tutto l'archivio.
        Le "altre" (cantieri...) hanno stato 2 quando nessuno le voleva al momento della lettura."""
        marks = ",".join("?" * len(categories))
        rows = self.b.query(
            f"SELECT data FROM ordinanze WHERE notify_state IN (1, 2, 3) AND category IN ({marks}) "
            "AND (json_extract(data, '$.end_date') IS NULL OR json_extract(data, '$.end_date') = '' "
            "OR json_extract(data, '$.end_date') >= ?)", (*categories, today.isoformat()))
        return [o for o in (ordinanza_from_json(r["data"]) for r in rows)
                if not o.is_expired(today) and o.parser_version != UNREAD]  # le mai lette (solo viste) non si riepilogano

    def all_ordinanze_with_provinces(self) -> list[Ordinanza]:
        """Ordinanze in archivio con almeno una provincia (per riempire l'atlante): quelle lette dal PDF."""
        rows = self.b.query("SELECT data FROM ordinanze WHERE json_extract(data, '$.provinces') NOT IN ('[]', '') "
                            "AND json_extract(data, '$.provinces') IS NOT NULL")
        return [ordinanza_from_json(r["data"]) for r in rows]

    def housekeeping(self, today: date, text_days: int = 60, deliveries_days: int = 90) -> tuple[int, int]:
        """Pulizia (una volta al giorno, di notte): svuota il testo dei PDF delle ordinanze scadute da più di
        text_days (restano dati e classificazione) e cancella le consegne concluse più vecchie di deliveries_days.
        Tiene il database (limite gratuito D1: 500 MB) stabile intorno a poche decine di MB."""
        cutoff = (today - timedelta(days=text_days)).isoformat()
        n_text = len(self.b.query(
            "SELECT ord_id FROM ordinanze WHERE text != '' AND json_extract(data, '$.end_date') != '' "
            "AND json_extract(data, '$.end_date') < ?", (cutoff,)))
        if n_text:
            self.b.query("UPDATE ordinanze SET text = '' WHERE text != '' AND json_extract(data, '$.end_date') != '' "
                         "AND json_extract(data, '$.end_date') < ?", (cutoff,))
        old = time.time() - deliveries_days * 86400
        n_deliv = len(self.b.query("SELECT ord_id FROM deliveries WHERE status != 'pending' AND created_at < ?", (old,)))
        if n_deliv:
            self.b.query("DELETE FROM deliveries WHERE status != 'pending' AND created_at < ?", (old,))
        return n_text, n_deliv

    def pending_ordinanze(self) -> list[Ordinanza]:
        rows = self.b.query("SELECT data FROM ordinanze WHERE notify_state=0 ORDER BY ord_id")
        return [ordinanza_from_json(r["data"]) for r in rows]

    def count_ordinanze(self) -> dict[str, int]:
        return {r["category"]: int(r["n"]) for r in
                self.b.query("SELECT category, COUNT(*) AS n FROM ordinanze GROUP BY category")}

    # --- utenti ---------------------------------------------------------
    def get_user(self, user_id: str) -> User | None:
        rows = self.b.query("SELECT * FROM users WHERE user_id=?", (user_id,))
        return _row_to_user(rows[0]) if rows else None

    def ensure_user(self, user_id: str) -> User:
        self.b.query(_UPSERT_USER, (user_id, time.time()))
        return self.get_user(user_id)  # type: ignore[return-value]

    def all_users(self) -> list[User]:
        return [_row_to_user(r) for r in self.b.query("SELECT * FROM users")]

    def mark_welcomed(self, user_id: str) -> None:
        self.b.query("UPDATE users SET welcomed_at=? WHERE user_id=?", (time.time(), user_id))

    def set_in_channel(self, user_id: str, value: bool) -> None:
        self.b.batch([
            (_UPSERT_USER, (user_id, time.time())),
            ("UPDATE users SET in_channel=?, updated_at=? WHERE user_id=?", (int(value), time.time(), user_id)),
        ])

    def set_paused(self, user_id: str, value: bool) -> None:
        self.b.query("UPDATE users SET paused=?, updated_at=? WHERE user_id=?", (int(value), time.time(), user_id))

    def save_preferences(self, user_id: str, *, all_italy: bool, regions: list[str], provinces: list[str],
                         want_closures: bool, want_speed: bool, want_all: bool = False,
                         all_regions: list[str] | None = None, all_provinces: list[str] | None = None) -> None:
        self.b.batch([
            (_UPSERT_USER, (user_id, time.time())),
            ("UPDATE users SET configured=1, paused=0, all_italy=?, regions=?, provinces=?, "
             "want_closures=?, want_speed=?, want_all=?, all_regions=?, all_provinces=?, updated_at=? "
             "WHERE user_id=?",
             (int(all_italy), json.dumps(sorted(regions)), json.dumps(sorted(provinces)),
              int(want_closures), int(want_speed), int(want_all),
              json.dumps(sorted(all_regions or [])), json.dumps(sorted(all_provinces or [])),
              time.time(), user_id)),
        ])

    # --- coda consegne --------------------------------------------------
    def enqueue(self, ord_id: int, user_ids: list[str], skip: bool) -> None:
        """Mette in coda i destinatari; per ULTIMO segna l'ordinanza come valutata."""
        now = time.time()
        stmts: list[Stmt] = [("INSERT OR IGNORE INTO deliveries(user_id, ord_id, created_at) VALUES(?,?,?)",
                              (u, ord_id, now)) for u in user_ids]
        stmts.append(("UPDATE ordinanze SET notify_state=? WHERE ord_id=?", (2 if skip else 1, ord_id)))
        self.b.batch(stmts)

    def delivered_ids(self, user_id: str) -> set[int]:
        """Ordinanze già messe in coda (in qualunque stato) per un utente o canale."""
        return {int(r["ord_id"]) for r in self.b.query("SELECT ord_id FROM deliveries WHERE user_id=?", (user_id,))}

    def record_deliveries(self, user_id: str, ord_ids: list[int], status: str) -> None:
        """Segna consegne fatte fuori dalla coda (riepilogo): così non si ripetono."""
        now = time.time()
        self.b.batch([("INSERT OR IGNORE INTO deliveries(user_id, ord_id, status, attempts, created_at, sent_at) "
                       "VALUES(?,?,?,1,?,?)", (user_id, o, status, now, now)) for o in ord_ids])

    def pending_deliveries(self) -> dict[str, list[int]]:
        out: dict[str, list[int]] = {}
        for r in self.b.query("SELECT user_id, ord_id FROM deliveries WHERE status='pending' ORDER BY ord_id"):
            out.setdefault(r["user_id"], []).append(int(r["ord_id"]))
        return out

    def mark_deliveries(self, user_id: str, ord_ids: list[int], status: str) -> None:
        now = time.time()
        self.b.batch([("UPDATE deliveries SET status=?, sent_at=?, attempts=attempts+1 WHERE user_id=? AND ord_id=?",
                       (status, now, user_id, o)) for o in ord_ids])

    def delivery_failed_attempt(self, user_id: str, ord_ids: list[int], max_attempts: int) -> None:
        self.b.batch([("UPDATE deliveries SET attempts=attempts+1, "
                       "status=CASE WHEN attempts+1>=? THEN 'failed' ELSE status END "
                       "WHERE user_id=? AND ord_id=?", (max_attempts, user_id, o)) for o in ord_ids])
