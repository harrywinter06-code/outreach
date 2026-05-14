import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from yield_system.config import settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_iso TEXT NOT NULL,
    experiment TEXT NOT NULL,
    action TEXT NOT NULL,
    cost_gbp REAL NOT NULL,
    expected TEXT NOT NULL,
    actual TEXT,
    call_id TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_ledger_ts ON ledger(ts_iso);
CREATE INDEX IF NOT EXISTS idx_ledger_exp ON ledger(experiment);

CREATE TABLE IF NOT EXISTS cre (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_iso TEXT NOT NULL,
    experiment TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    amount_gbp REAL NOT NULL,
    stripe_event_id TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cre_ts ON cre(ts_iso);
CREATE INDEX IF NOT EXISTS idx_cre_exp ON cre(experiment);

CREATE TABLE IF NOT EXISTS api_call_hashes (
    hash TEXT PRIMARY KEY,
    ts_iso TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 1,
    last_state_hash TEXT
);

CREATE TABLE IF NOT EXISTS customers (
    id TEXT PRIMARY KEY,
    experiment TEXT NOT NULL,
    stripe_customer_id TEXT,
    email TEXT,
    api_key TEXT UNIQUE NOT NULL,
    created_iso TEXT NOT NULL,
    plan TEXT NOT NULL DEFAULT 'free'
);
CREATE INDEX IF NOT EXISTS idx_customers_apikey ON customers(api_key);

CREATE TABLE IF NOT EXISTS webhook_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token TEXT NOT NULL,
    body_sha256 TEXT NOT NULL,
    idempotency_key TEXT,
    payload BLOB NOT NULL,
    headers TEXT NOT NULL,
    received_iso TEXT NOT NULL,
    UNIQUE(token, body_sha256, idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_wh_token ON webhook_events(token);

CREATE TABLE IF NOT EXISTS sanctions_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    name TEXT NOT NULL,
    name_normalized TEXT NOT NULL,
    aliases TEXT,
    program TEXT,
    added_iso TEXT NOT NULL,
    UNIQUE(source, source_id)
);
CREATE INDEX IF NOT EXISTS idx_sanc_name ON sanctions_entries(name_normalized);

CREATE TABLE IF NOT EXISTS sanctions_subs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id TEXT NOT NULL,
    watchlist_name TEXT NOT NULL,
    name_normalized TEXT NOT NULL,
    webhook_url TEXT NOT NULL,
    created_iso TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sub_name ON sanctions_subs(name_normalized);
"""


def _db_path() -> Path:
    return settings().data_dir / "yield.db"


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(_db_path(), isolation_level=None, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_schema() -> None:
    with connect() as c:
        c.executescript(_SCHEMA)
