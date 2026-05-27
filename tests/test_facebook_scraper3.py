"""Tests for the RapidAPI-based Facebook scraper.

We never actually hit RapidAPI in the test suite — every external call is
patched. That keeps tests fast, free, and reliable across CI/local.

What we verify:
  1. Page-ID lookup hits /search/pages and pulls the right id field.
  2. Page-posts call hits /page/posts with the resolved id.
  3. Posts are filtered against the home-loan keyword list (relevance filter
     reused from scrapers/facebook.py).
  4. Output rows match the schema collector.save() expects.
  5. No RAPIDAPI_KEY → scrape() returns [] cleanly (no crash).
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest


# ─── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def mock_requests(monkeypatch):
    """Replace ``requests.get`` with a lookup table keyed by URL substring."""
    calls = []

    def make_response(json_payload: dict, status: int = 200):
        m = MagicMock()
        m.json.return_value = json_payload
        m.status_code = status
        m.raise_for_status = MagicMock()
        return m

    response_map = {
        # /search/pages?query=Vietcombank → returns numeric ID
        "/search/pages": make_response({
            "results": [{
                "facebook_id": "111222333",
                "name": "Vietcombank",
                "url": "https://www.facebook.com/Vietcombank",
            }],
        }),
        # /page/posts?page_id=111222333 → two posts, one relevant + one not
        "/page/posts": make_response({
            "results": [
                {
                    "post_id":  "p001",
                    "message":  "Ưu đãi lãi suất vay mua nhà chỉ từ 5.5%/năm. Liên hệ ngay!",
                    "url":      "https://facebook.com/Vietcombank/posts/p001",
                    "timestamp": 1716800000,
                },
                {
                    "post_id":  "p002",
                    "message":  "Chúc mừng năm mới các bạn — chúc thành công!",
                    "url":      "https://facebook.com/Vietcombank/posts/p002",
                    "timestamp": 1716700000,
                },
            ],
        }),
    }

    def fake_get(url, **kwargs):
        calls.append({"url": url, "params": kwargs.get("params", {})})
        for key, response in response_map.items():
            if key in url:
                return response
        # Unmatched URL — return empty result so the test doesn't hang on a hit.
        return make_response({"results": []})

    monkeypatch.setattr("requests.get", fake_get)
    return calls


# ─── Tests ──────────────────────────────────────────────────────────────────

def test_no_api_key_returns_empty(monkeypatch):
    """When RAPIDAPI_KEY is empty/unset, the scraper must no-op (no crash).

    SUBTLETY: the module calls ``load_dotenv(override=True)`` at import time
    to defeat a stale-shell-empty-var bug (see test_dotenv_override.py). That
    means *any* setenv/delenv we do BEFORE importing the module gets
    overwritten by the real .env value. We sidestep this by:
      1. Letting the module import (and load .env) happen first.
      2. THEN monkeypatching the env to "" so ``_api_key()`` returns None.
    monkeypatch.setenv records the original value and restores it on teardown,
    so the next test still sees the real key.
    """
    from scrapers import facebook_scraper3
    monkeypatch.setenv("RAPIDAPI_KEY", "")   # blank AFTER import

    result = facebook_scraper3.scrape()
    assert result == [], "Without a key, scrape() must return [] and never raise."


def test_scrape_resolves_page_id_then_fetches_posts(monkeypatch, mock_requests):
    """End-to-end happy path: search/pages → page/posts → filtered articles."""
    monkeypatch.setenv("RAPIDAPI_KEY", "test-key-123")

    # Patch sources.yaml lookup to a single page so the test is deterministic.
    from pipeline import config_loader
    monkeypatch.setattr(
        config_loader, "load_sources",
        lambda: {"facebook_pages": [{"name": "Vietcombank", "page_id": "Vietcombank"}]},
    )

    from scrapers import facebook_scraper3
    import importlib
    importlib.reload(facebook_scraper3)

    articles = facebook_scraper3.scrape()

    # Only the relevant post should survive — the "Happy New Year" one has no
    # home-loan keywords and must be filtered out.
    assert len(articles) == 1, f"Expected 1 relevant article, got {len(articles)}: {articles}"
    a = articles[0]

    # Schema compatible with pipeline.collector.save()
    assert a["source"] == "Vietcombank"
    assert a["title"], "title must not be empty"
    assert "lãi suất" in a["summary"].lower() or "vay mua nhà" in a["summary"].lower()
    assert a["url"].startswith("https://facebook.com/")
    assert a["scraped_at"], "scraped_at must be set"

    # Verify both endpoints were hit, in the right order, with the right params
    urls_hit = [c["url"] for c in mock_requests]
    assert any("/search/pages" in u for u in urls_hit), \
        f"Expected /search/pages call. URLs hit: {urls_hit}"
    assert any("/page/posts" in u for u in urls_hit), \
        f"Expected /page/posts call. URLs hit: {urls_hit}"

    # /page/posts must be called with the resolved numeric ID, not the username
    posts_call = next(c for c in mock_requests if "/page/posts" in c["url"])
    assert posts_call["params"].get("page_id") == "111222333", (
        f"page/posts should receive the resolved id 111222333, "
        f"got {posts_call['params']}"
    )


def test_scrape_survives_search_pages_failure(monkeypatch):
    """If /search/pages returns no results for a name, skip that page — don't crash."""
    monkeypatch.setenv("RAPIDAPI_KEY", "test-key-123")

    from pipeline import config_loader
    monkeypatch.setattr(
        config_loader, "load_sources",
        lambda: {"facebook_pages": [{"name": "NonexistentBank", "page_id": "NonexistentBank"}]},
    )

    def empty_get(url, **kwargs):
        m = MagicMock()
        m.json.return_value = {"results": []}
        m.status_code = 200
        m.raise_for_status = MagicMock()
        return m

    monkeypatch.setattr("requests.get", empty_get)

    from scrapers import facebook_scraper3
    import importlib
    importlib.reload(facebook_scraper3)

    # Must not raise — just returns empty
    result = facebook_scraper3.scrape()
    assert result == []


def test_scrape_handles_http_error(monkeypatch):
    """A 429 / 503 from RapidAPI must skip the page, not crash the whole run."""
    monkeypatch.setenv("RAPIDAPI_KEY", "test-key-123")

    from pipeline import config_loader
    monkeypatch.setattr(
        config_loader, "load_sources",
        lambda: {"facebook_pages": [{"name": "Vietcombank", "page_id": "Vietcombank"}]},
    )

    import requests as _real_requests
    def boom(url, **kwargs):
        raise _real_requests.exceptions.RequestException("simulated 429")

    monkeypatch.setattr("requests.get", boom)

    from scrapers import facebook_scraper3
    import importlib
    importlib.reload(facebook_scraper3)

    result = facebook_scraper3.scrape()
    assert result == []
