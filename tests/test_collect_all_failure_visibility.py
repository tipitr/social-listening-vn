"""A categorizer crash after successful inserts must fail the run (red check),
not exit green with a day of unlabeled articles."""

from __future__ import annotations

import pytest


def test_categorizer_failure_after_inserts_raises(monkeypatch):
    from pipeline import collector

    monkeypatch.setattr(collector, "init_db", lambda: None)
    monkeypatch.setattr(collector, "save", lambda articles: 5)        # 5 rows landed
    monkeypatch.setattr(collector, "log_usage", lambda *a, **k: None)
    # No scraper env vars → no facebook/rapidapi branches
    for var in ("FIRECRAWL_API_KEY", "FACEBOOK_ACCESS_TOKEN", "FACEBOOK_APP_ID", "RAPIDAPI_KEY"):
        monkeypatch.delenv(var, raising=False)

    # news + forums scrapers return nothing (we fake save() anyway)
    import scrapers.news, scrapers.forums
    monkeypatch.setattr(scrapers.news, "scrape", lambda: [])
    monkeypatch.setattr(scrapers.forums, "scrape", lambda: [])

    # categorizer blows up
    import pipeline.categorizer
    def boom():
        raise RuntimeError("API key expired")
    monkeypatch.setattr(pipeline.categorizer, "run", boom)

    with pytest.raises(RuntimeError, match="Categorizer failed after collect"):
        collector.collect_all()


def test_zero_inserts_does_not_raise(monkeypatch):
    from pipeline import collector

    monkeypatch.setattr(collector, "init_db", lambda: None)
    monkeypatch.setattr(collector, "save", lambda articles: 0)
    monkeypatch.setattr(collector, "log_usage", lambda *a, **k: None)
    for var in ("FIRECRAWL_API_KEY", "FACEBOOK_ACCESS_TOKEN", "FACEBOOK_APP_ID", "RAPIDAPI_KEY"):
        monkeypatch.delenv(var, raising=False)

    import scrapers.news, scrapers.forums
    monkeypatch.setattr(scrapers.news, "scrape", lambda: [])
    monkeypatch.setattr(scrapers.forums, "scrape", lambda: [])

    assert collector.collect_all() == 0   # no categorize attempt, no raise
