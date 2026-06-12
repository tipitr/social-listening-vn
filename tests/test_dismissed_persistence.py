"""Dismissed-ids persistence: the reports-table round trip used by the dashboard."""

from __future__ import annotations

import json


def _fresh_sqlite(monkeypatch, tmp_path):
    from pipeline import db
    monkeypatch.setattr(db, "IS_POSTGRES", False)
    monkeypatch.setattr(db, "SQLITE_PATH", tmp_path / "test.db")
    return db


def test_dismissed_ids_round_trip(monkeypatch, tmp_path):
    db = _fresh_sqlite(monkeypatch, tmp_path)
    db.init_schema()

    ids = sorted(int(i) for i in {3, 1, 2})
    db.save_report("dismissed_article_ids", json.dumps(ids))

    loaded = set(json.loads(db.get_report("dismissed_article_ids")))
    assert loaded == {1, 2, 3}


def test_get_report_missing_key_returns_none(monkeypatch, tmp_path):
    db = _fresh_sqlite(monkeypatch, tmp_path)
    db.init_schema()
    assert db.get_report("dismissed_article_ids") is None
