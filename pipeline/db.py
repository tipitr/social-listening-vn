"""Database connection layer — speaks both SQLite (local dev) and Postgres (production).

How it picks a backend:
    DATABASE_URL set to a postgres:// or postgresql:// URL  →  Postgres (e.g. Supabase)
    DATABASE_URL empty / unset                              →  SQLite at data/social_listening.db

Why this exists: the project was originally written against SQLite, but for
deployment we need Postgres so multiple processes (Streamlit Cloud + GitHub
Actions cron) can share the same database. This module makes the swap a
one-line env change rather than a rewrite.

What this module wraps:
    - connect()      : context manager yielding a "sqlite-like" connection
    - adapt_sql()    : translates :name placeholders to %(name)s for psycopg2
    - IS_POSTGRES    : True iff DATABASE_URL points at Postgres
    - init_schema()  : creates the articles + usage_log tables (idempotent)

The conn object yielded by connect() exposes .execute(sql, params),
.executemany(sql, rows), .commit() — same shape as sqlite3.Connection,
so the rest of the codebase doesn't care which backend is active.
"""

from __future__ import annotations

import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
IS_POSTGRES = DATABASE_URL.startswith(("postgres://", "postgresql://"))

SQLITE_PATH = Path(__file__).parent.parent / "data" / "social_listening.db"

if IS_POSTGRES:
    import psycopg2
    import psycopg2.extras

# Matches :name in SQL but not inside string literals like 'a:b' — we don't
# have any such literals in our queries, so a simple regex is enough.
_NAMED_PARAM = re.compile(r":(\w+)")


def adapt_sql(query: str) -> str:
    """Translate SQLite-style placeholders to psycopg2-style if running on Postgres."""
    if not IS_POSTGRES:
        return query
    query = _NAMED_PARAM.sub(r"%(\1)s", query)
    query = query.replace("?", "%s")
    return query


# ── Postgres shim ─────────────────────────────────────────────────────────────

class _PgCursor:
    """Wraps psycopg2 cursor so results look like dicts (sqlite3.Row behaviour)."""

    def __init__(self, cursor):
        self._c = cursor

    def fetchall(self) -> list[dict]:
        return [dict(r) for r in self._c.fetchall()]

    def fetchone(self) -> dict | None:
        row = self._c.fetchone()
        return dict(row) if row else None

    @property
    def rowcount(self) -> int:
        return self._c.rowcount


class _PgConn:
    """Makes a psycopg2 connection feel like sqlite3.Connection for our usage."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, query: str, params: Any = None) -> _PgCursor:
        cursor = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute(adapt_sql(query), params or {})
        return _PgCursor(cursor)

    def executemany(self, query: str, params_seq) -> _PgCursor:
        cursor = self._conn.cursor()
        cursor.executemany(adapt_sql(query), params_seq)
        return _PgCursor(cursor)

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()


# ── Public connection helper ──────────────────────────────────────────────────

@contextmanager
def connect() -> Iterator[Any]:
    """Yield a connection. Commits on clean exit, rolls back on exception."""
    if IS_POSTGRES:
        raw = psycopg2.connect(DATABASE_URL)
        try:
            yield _PgConn(raw)
            raw.commit()
        except Exception:
            raw.rollback()
            raise
        finally:
            raw.close()
    else:
        SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(SQLITE_PATH))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


# ── Pandas helper ─────────────────────────────────────────────────────────────

def read_sql_df(query: str, params: dict | None = None):
    """Run a SELECT and return a pandas DataFrame.

    Pandas + psycopg2 raises a SQLAlchemy warning but works; we suppress it
    by going through the raw connection in both modes.
    """
    import pandas as pd
    import warnings

    if IS_POSTGRES:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            raw = psycopg2.connect(DATABASE_URL)
            try:
                return pd.read_sql_query(adapt_sql(query), raw, params=params or {})
            finally:
                raw.close()
    else:
        SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(SQLITE_PATH)) as conn:
            return pd.read_sql_query(query, conn, params=params or {})


# ── Schema ────────────────────────────────────────────────────────────────────

_CREATE_ARTICLES_SQLITE = """
CREATE TABLE IF NOT EXISTS articles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT    NOT NULL,
    source_url  TEXT,
    title       TEXT    NOT NULL,
    summary     TEXT,
    url         TEXT    UNIQUE NOT NULL,
    category    TEXT,
    sentiment   TEXT,
    intent      TEXT,
    summary_vi  TEXT,
    summary_en  TEXT,
    scraped_at  TEXT    NOT NULL,
    created_at  TEXT    NOT NULL
);
"""

_CREATE_ARTICLES_PG = """
CREATE TABLE IF NOT EXISTS articles (
    id          BIGSERIAL PRIMARY KEY,
    source      TEXT      NOT NULL,
    source_url  TEXT,
    title       TEXT      NOT NULL,
    summary     TEXT,
    url         TEXT      UNIQUE NOT NULL,
    category    TEXT,
    sentiment   TEXT,
    intent      TEXT,
    summary_vi  TEXT,
    summary_en  TEXT,
    scraped_at  TEXT      NOT NULL,
    created_at  TEXT      NOT NULL
);
"""

_CREATE_USAGE_LOG_SQLITE = """
CREATE TABLE IF NOT EXISTS usage_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    service         TEXT    NOT NULL,
    model           TEXT,
    tokens_in       INTEGER DEFAULT 0,
    tokens_out      INTEGER DEFAULT 0,
    cost_usd        REAL    DEFAULT 0,
    items_processed INTEGER DEFAULT 0,
    created_at      TEXT    NOT NULL
);
"""

_CREATE_USAGE_LOG_PG = """
CREATE TABLE IF NOT EXISTS usage_log (
    id              BIGSERIAL PRIMARY KEY,
    service         TEXT      NOT NULL,
    model           TEXT,
    tokens_in       INTEGER   DEFAULT 0,
    tokens_out      INTEGER   DEFAULT 0,
    cost_usd        NUMERIC   DEFAULT 0,
    items_processed INTEGER   DEFAULT 0,
    created_at      TEXT      NOT NULL
);
"""

# Migration columns added after v1 — applied to existing DBs on each boot.
_MIGRATION_COLS = {
    "sentiment":  "TEXT",
    "intent":     "TEXT",
    "summary_vi": "TEXT",
    "summary_en": "TEXT",
}


def init_schema() -> None:
    """Create tables if missing and add any newer columns. Safe to call repeatedly."""
    articles_sql  = _CREATE_ARTICLES_PG  if IS_POSTGRES else _CREATE_ARTICLES_SQLITE
    usage_log_sql = _CREATE_USAGE_LOG_PG if IS_POSTGRES else _CREATE_USAGE_LOG_SQLITE

    with connect() as conn:
        conn.execute(articles_sql)
        conn.execute(usage_log_sql)

        if IS_POSTGRES:
            for col, dtype in _MIGRATION_COLS.items():
                conn.execute(
                    f"ALTER TABLE articles ADD COLUMN IF NOT EXISTS {col} {dtype}"
                )
        else:
            existing = {row[1] for row in conn.execute("PRAGMA table_info(articles)").fetchall()}
            for col, dtype in _MIGRATION_COLS.items():
                if col not in existing:
                    conn.execute(f"ALTER TABLE articles ADD COLUMN {col} {dtype}")


def backend_name() -> str:
    return "postgres" if IS_POSTGRES else "sqlite"
