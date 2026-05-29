"""When a Facebook page has its numeric ``fb_id`` set in sources.yaml,
the RapidAPI scraper must skip the ``/search/pages`` lookup and call
``/page/posts`` directly with the cached id.

WHY
The Facebook Scraper3 free tier on RapidAPI is much tighter than the
listing implies — we observed 429s after a handful of calls. Each
monitored page currently costs **2** API calls per cron run:

  1. ``/search/pages?query=<name>`` → resolves a numeric Facebook id
  2. ``/page/posts?page_id=<id>``    → returns recent posts

The numeric id never changes for a given page, so step 1 only needs to
happen ONCE — ever. By pinning the resolved id in
``config/sources.yaml`` (a ``fb_id`` field per entry), every
subsequent run drops to 1 call per page, halving the quota burn.

CONTRACT
  • Entry with ``fb_id`` → skip /search/pages entirely. Call
    /page/posts with the configured id.
  • Entry without ``fb_id`` → fall back to /search/pages, log the
    resolved id so the operator can paste it into sources.yaml.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def _build_mock_requests():
    """Build a fake requests.get that tracks every URL hit."""
    calls = []

    def fake_get(url, **kwargs):
        calls.append({"url": url, "params": kwargs.get("params", {})})
        m = MagicMock()
        m.status_code = 200
        m.raise_for_status = MagicMock()
        if "/page/posts" in url:
            m.json.return_value = {
                "results": [
                    {
                        "post_id": "p1",
                        "message": "Vay mua nhà lãi suất ưu đãi chỉ từ 5%",
                        "url": "https://facebook.com/Vietcombank/posts/p1",
                        "timestamp": 1716800000,
                    },
                ],
            }
        elif "/search/pages" in url:
            m.json.return_value = {
                "results": [{"facebook_id": "999111", "name": "Vietcombank"}],
            }
        else:
            m.json.return_value = {"results": []}
        return m

    return calls, fake_get


def test_cached_fb_id_skips_search_pages_call(monkeypatch):
    """A page configured with ``fb_id`` must NOT trigger /search/pages."""
    monkeypatch.setenv("RAPIDAPI_KEY", "test-key")
    calls, fake_get = _build_mock_requests()
    monkeypatch.setattr("requests.get", fake_get)

    # Page list with fb_id already pinned
    monkeypatch.setattr("scrapers.facebook_scraper3.load_sources", lambda: {
        "facebook_pages": [
            {"name": "Vietcombank", "page_id": "Vietcombank", "fb_id": "999111"},
        ],
    })

    from scrapers import facebook_scraper3
    articles = facebook_scraper3.scrape()

    urls_hit = [c["url"] for c in calls]
    assert not any("/search/pages" in u for u in urls_hit), (
        f"With fb_id pinned, /search/pages must be SKIPPED. URLs hit: {urls_hit}"
    )
    assert any("/page/posts" in u for u in urls_hit), (
        "Still needs to call /page/posts to get the actual content."
    )
    posts_call = next(c for c in calls if "/page/posts" in c["url"])
    assert posts_call["params"].get("page_id") == "999111", (
        f"/page/posts must use the cached id verbatim, got {posts_call['params']}"
    )
    assert len(articles) == 1


def test_missing_fb_id_falls_back_to_search(monkeypatch):
    """Backwards-compat: entries without fb_id still resolve via /search/pages."""
    monkeypatch.setenv("RAPIDAPI_KEY", "test-key")
    calls, fake_get = _build_mock_requests()
    monkeypatch.setattr("requests.get", fake_get)

    monkeypatch.setattr("scrapers.facebook_scraper3.load_sources", lambda: {
        "facebook_pages": [
            {"name": "Vietcombank", "page_id": "Vietcombank"},  # no fb_id
        ],
    })

    from scrapers import facebook_scraper3
    facebook_scraper3.scrape()

    urls_hit = [c["url"] for c in calls]
    assert any("/search/pages" in u for u in urls_hit), (
        f"Without fb_id, /search/pages must fire. URLs hit: {urls_hit}"
    )
    assert any("/page/posts" in u for u in urls_hit)
