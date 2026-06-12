"""categorized_at: stamp every labeled row, backfill history on migration."""

from __future__ import annotations

import importlib


def _fresh_sqlite(monkeypatch, tmp_path):
    """Point pipeline.db at a throwaway SQLite file regardless of local .env."""
    from pipeline import db
    monkeypatch.setattr(db, "IS_POSTGRES", False)
    monkeypatch.setattr(db, "SQLITE_PATH", tmp_path / "test.db")
    return db


def test_init_schema_adds_and_backfills_categorized_at(monkeypatch, tmp_path):
    db = _fresh_sqlite(monkeypatch, tmp_path)
    db.init_schema()

    # Simulate a pre-migration row that was already categorized
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO articles (source, title, url, sentiment, summary_en, "
            "scraped_at, created_at) VALUES ('t', 'a', 'http://x/1', 'neutral', "
            "'s', '2026-01-01T00:00:00', '2026-01-01T00:00:00')"
        )
        conn.execute("UPDATE articles SET categorized_at = NULL")

    db.init_schema()   # re-run → backfill should stamp the labeled row

    with db.connect() as conn:
        row = conn.execute(
            "SELECT categorized_at FROM articles WHERE url = 'http://x/1'"
        ).fetchone()
    assert dict(row)["categorized_at"] == "2026-01-01T00:00:00", \
        "already-labeled rows must be backfilled from created_at"


def test_validate_stamps_categorized_at(monkeypatch):
    from pipeline import categorizer
    importlib.reload(categorizer)
    out = categorizer._validate({"id": 7, "sentiment": "positive",
                                 "category": "promotion", "intent": "promotion",
                                 "summary_vi": "a", "summary_en": "b"})
    assert out["categorized_at"], "_validate must stamp categorized_at"

    out_inbox = categorizer._validate_inbox({"id": 8, "topic": "other",
                                             "sentiment": "neutral",
                                             "summary_vi": "a", "summary_en": "b"})
    assert out_inbox["categorized_at"], "_validate_inbox must stamp categorized_at"
