"""One-time data migration: copy the local SQLite DB to a Postgres DB (e.g. Supabase).

Usage:
    export DATABASE_URL='postgresql://user:pass@host:port/dbname'
    python scripts/migrate_sqlite_to_postgres.py

What it does:
    1. Connects to the LOCAL SQLite file at data/social_listening.db
    2. Connects to the Postgres URL in DATABASE_URL
    3. Creates the Postgres schema (idempotent)
    4. Copies every article and usage_log row
    5. Skips rows whose URL already exists in Postgres (so it's safe to re-run)

Run this ONCE before you flip the production app over to Postgres.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SQLITE_PATH = ROOT / "data" / "social_listening.db"


def _require_postgres_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url.startswith(("postgres://", "postgresql://")):
        raise SystemExit(
            "DATABASE_URL must be set to a postgres:// URL.\n"
            "Find this in Supabase → Project Settings → Database → Connection string."
        )
    return url


def _check_sqlite_exists() -> None:
    if not SQLITE_PATH.exists():
        raise SystemExit(
            f"No local SQLite file at {SQLITE_PATH}.\n"
            "Nothing to migrate — start fresh in Postgres by running the app."
        )


def _read_sqlite_rows(table: str) -> list[dict]:
    with sqlite3.connect(str(SQLITE_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()
    return [dict(r) for r in rows]


def _insert_articles(pg_conn, rows: list[dict]) -> int:
    """Insert rows skipping duplicates by url. Returns count actually inserted."""
    if not rows:
        return 0
    inserted = 0
    sql = """
        INSERT INTO articles
            (source, source_url, title, summary, url, category, sentiment,
             intent, summary_vi, summary_en, scraped_at, created_at)
        VALUES (%(source)s, %(source_url)s, %(title)s, %(summary)s, %(url)s,
                %(category)s, %(sentiment)s, %(intent)s, %(summary_vi)s,
                %(summary_en)s, %(scraped_at)s, %(created_at)s)
        ON CONFLICT (url) DO NOTHING
    """
    cursor = pg_conn.cursor()
    for row in rows:
        cursor.execute(sql, {
            "source":     row.get("source", ""),
            "source_url": row.get("source_url", ""),
            "title":      row.get("title", ""),
            "summary":    row.get("summary", ""),
            "url":        row.get("url", ""),
            "category":   row.get("category"),
            "sentiment":  row.get("sentiment"),
            "intent":     row.get("intent"),
            "summary_vi": row.get("summary_vi"),
            "summary_en": row.get("summary_en"),
            "scraped_at": row.get("scraped_at"),
            "created_at": row.get("created_at"),
        })
        inserted += cursor.rowcount  # 1 if inserted, 0 if skipped
    return inserted


def _insert_usage_log(pg_conn, rows: list[dict]) -> int:
    if not rows:
        return 0
    sql = """
        INSERT INTO usage_log
            (service, model, tokens_in, tokens_out, cost_usd, items_processed, created_at)
        VALUES (%(service)s, %(model)s, %(tokens_in)s, %(tokens_out)s,
                %(cost_usd)s, %(items_processed)s, %(created_at)s)
    """
    cursor = pg_conn.cursor()
    cursor.executemany(sql, rows)
    return len(rows)


def main() -> None:
    pg_url = _require_postgres_url()
    _check_sqlite_exists()

    print(f"Source: {SQLITE_PATH}")
    print(f"Target: {pg_url.split('@')[-1]}  (postgres)")
    print()

    # Create schema on target first
    print("→ Creating schema on Postgres if missing…")
    from pipeline import db
    if not db.IS_POSTGRES:
        raise SystemExit("DATABASE_URL not picked up — restart your shell.")
    db.init_schema()
    print("  done")

    articles = _read_sqlite_rows("articles")
    print(f"→ Read {len(articles):,} articles from SQLite")

    try:
        usage = _read_sqlite_rows("usage_log")
    except sqlite3.OperationalError:
        usage = []
    print(f"→ Read {len(usage):,} usage_log rows from SQLite")
    print()

    import psycopg2
    pg_conn = psycopg2.connect(pg_url)
    try:
        a_inserted = _insert_articles(pg_conn, articles)
        u_inserted = _insert_usage_log(pg_conn, usage)
        pg_conn.commit()
    except Exception:
        pg_conn.rollback()
        raise
    finally:
        pg_conn.close()

    print(f"✓ articles  : {a_inserted:,} new (skipped {len(articles) - a_inserted:,} dupes)")
    print(f"✓ usage_log : {u_inserted:,} inserted")
    print()
    print("Migration complete. Verify by loading the dashboard with DATABASE_URL set.")


if __name__ == "__main__":
    main()
