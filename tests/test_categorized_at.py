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

    # Negative guard: an UNLABELED row (sentiment NULL) must NOT be stamped by
    # the backfill — it still needs to go through the categorizer.
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO articles (source, title, url, scraped_at, created_at) "
            "VALUES ('t', 'b', 'http://x/unlabeled', '2026-01-03T00:00:00', '2026-01-03T00:00:00')"
        )

    db.init_schema()   # re-run → backfill must leave the unlabeled row alone

    with db.connect() as conn:
        row = conn.execute(
            "SELECT categorized_at FROM articles WHERE url = 'http://x/unlabeled'"
        ).fetchone()
    assert dict(row)["categorized_at"] is None, \
        "backfill must not stamp rows the categorizer still needs to fetch"


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


def test_update_article_sql_writes_categorized_at(monkeypatch, tmp_path):
    db = _fresh_sqlite(monkeypatch, tmp_path)
    db.init_schema()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO articles (source, title, url, scraped_at, created_at) "
            "VALUES ('t', 'a', 'http://x/2', '2026-01-02T00:00:00', '2026-01-02T00:00:00')"
        )
        row_id = conn.execute(
            "SELECT id FROM articles WHERE url = 'http://x/2'"
        ).fetchone()[0]

    from pipeline import categorizer
    validated = categorizer._validate({
        "id": row_id, "sentiment": "positive", "category": "promotion",
        "intent": "promotion", "summary_vi": "a", "summary_en": "b",
    })
    categorizer._update_batch(categorizer._UPDATE_ARTICLE, [validated])

    with db.connect() as conn:
        row = dict(conn.execute(
            "SELECT sentiment, categorized_at FROM articles WHERE id = :id",
            {"id": row_id},
        ).fetchone())
    assert row["sentiment"] == "positive"
    assert row["categorized_at"], "the real UPDATE SQL must stamp categorized_at"
