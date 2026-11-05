-- Schema unico, usato da:
--   * Cloudflare D1 (database condiviso tra Worker e GitHub Actions)
--   * SQLite locale (test e prove sul PC)
-- Creazione su D1:  npx wrangler d1 execute anas-bot --remote --file=../anas_bot/schema.sql

CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- id saltati nella numerazione ANAS, da ricontrollare per qualche ora
CREATE TABLE IF NOT EXISTS missing_ids (
    ord_id INTEGER PRIMARY KEY,
    first_missed_at REAL NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 1
);

-- notify_state: 0 da valutare, 1 messa in coda, 2 da non notificare, 3 già in vigore all'installazione (mai notificata)
CREATE TABLE IF NOT EXISTS ordinanze (
    ord_id INTEGER PRIMARY KEY,
    fetched_at REAL NOT NULL,
    category TEXT NOT NULL,
    data TEXT NOT NULL,
    text TEXT,
    notify_state INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_ord_state ON ordinanze(notify_state);

-- iscritti: scritti dal Worker (preferenze) e dal job (riallineamento canale)
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    in_channel INTEGER NOT NULL DEFAULT 1,
    paused INTEGER NOT NULL DEFAULT 0,
    configured INTEGER NOT NULL DEFAULT 0,
    all_italy INTEGER NOT NULL DEFAULT 0,
    regions TEXT NOT NULL DEFAULT '[]',
    provinces TEXT NOT NULL DEFAULT '[]',
    want_closures INTEGER NOT NULL DEFAULT 1,
    want_speed INTEGER NOT NULL DEFAULT 1,
    want_all INTEGER NOT NULL DEFAULT 0,  -- anche cantieri e restringimenti (tutte le altre ordinanze)
    all_regions TEXT NOT NULL DEFAULT '[]',   -- zone dei cantieri, se diverse da quelle sopra (vuote = le stesse)
    all_provinces TEXT NOT NULL DEFAULT '[]',
    welcomed_at REAL,
    updated_at REAL
);

-- atlante imparato: strada + chilometri (in metri, -1 = ignoti) -> province, dai PDF letti (anas_bot/atlante.py)
CREATE TABLE IF NOT EXISTS atlante (
    road TEXT NOT NULL,
    km_from INTEGER NOT NULL,
    km_to INTEGER NOT NULL,
    provinces TEXT NOT NULL,
    ord_id INTEGER NOT NULL,
    PRIMARY KEY (road, km_from, km_to)
);

-- coda dei messaggi: status pending | sent | failed | skipped
CREATE TABLE IF NOT EXISTS deliveries (
    user_id TEXT NOT NULL,
    ord_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    sent_at REAL,
    PRIMARY KEY (user_id, ord_id)
);
CREATE INDEX IF NOT EXISTS ix_deliv_status ON deliveries(status);
