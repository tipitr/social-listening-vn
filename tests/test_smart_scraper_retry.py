"""Tests for smart_scraper._fetch_plain retry loop and bot-block short-circuit.

Mirrors the style of tests/test_fetch_retry.py: patch
scrapers.smart_scraper.requests.get and scrapers.smart_scraper.time.sleep.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import requests


# ── helpers ───────────────────────────────────────────────────────────────────

def _ok_response():
    """200 response with plain HTML that passes _needs_firecrawl cleanly.

    Requirements from _needs_firecrawl:
      - status_code NOT in (403, 429, 503)
      - text[:3000].lower() must not contain any _CHALLENGE_SIGNALS
      - soup must have >= 5 <a href=...> links
      - text must not contain any _JS_FRAMEWORK_SIGNALS (__next, _next/, etc.)
    """
    links = "".join(f'<a href="/page-{i}">link {i}</a>' for i in range(10))
    body = f"<html><body><p>Tin tuc vay mua nha hom nay.</p>{links}</body></html>"
    resp = MagicMock()
    resp.status_code = 200
    resp.text = body
    resp.encoding = "utf-8"
    return resp


def _blocked_response():
    """403 response — triggers _needs_firecrawl immediately (no retry)."""
    resp = MagicMock()
    resp.status_code = 403
    resp.text = "Forbidden"
    resp.encoding = "utf-8"
    return resp


# ── tests ─────────────────────────────────────────────────────────────────────

def test_bot_detection_short_circuits_no_retry(monkeypatch):
    """A 403 response triggers _needs_firecrawl → returns (None, reason) after
    exactly ONE requests.get call, with no backoff sleep beyond the politeness delay."""
    waits = []
    monkeypatch.setattr("scrapers.smart_scraper.time.sleep", lambda s: waits.append(s))

    with patch("scrapers.smart_scraper.requests.get") as mock_get:
        mock_get.return_value = _blocked_response()

        from scrapers.smart_scraper import _fetch_plain
        soup, reason = _fetch_plain("https://example.com", delay=0)

    assert soup is None
    assert reason is not None, "reason must be a non-None string explaining the block"
    assert mock_get.call_count == 1, "should not retry on bot-detection"
    # Only the politeness delay (0) should have fired — no backoff sleeps
    assert waits == [0], f"unexpected sleeps beyond politeness delay: {waits}"


def test_connection_error_retries_then_succeeds(monkeypatch):
    """A transient ConnectionError on the first attempt is retried.
    Second attempt succeeds → returns (soup, None) with backoff sleep of 2s."""
    waits = []
    monkeypatch.setattr("scrapers.smart_scraper.time.sleep", lambda s: waits.append(s))

    with patch("scrapers.smart_scraper.requests.get") as mock_get:
        mock_get.side_effect = [requests.ConnectionError("blip"), _ok_response()]

        from scrapers.smart_scraper import _fetch_plain
        soup, reason = _fetch_plain("https://example.com", delay=1)

    assert soup is not None, "should return a parsed soup on eventual success"
    assert reason is None, "reason must be None when plain fetch succeeds"
    assert mock_get.call_count == 2
    # waits[0] = politeness delay (1), waits[1] = backoff after attempt 0 (2s)
    assert 2 in waits, "backoff sleep of 2s must be recorded after first failure"


def test_total_failure_returns_none_never_raises(monkeypatch):
    """All 3 attempts raise ConnectionError → returns (None, reason) where
    reason starts with 'request failed'. Must not raise, must make 3 GET calls."""
    waits = []
    monkeypatch.setattr("scrapers.smart_scraper.time.sleep", lambda s: waits.append(s))

    with patch("scrapers.smart_scraper.requests.get") as mock_get:
        mock_get.side_effect = requests.ConnectionError("dead site")

        from scrapers.smart_scraper import _fetch_plain
        soup, reason = _fetch_plain("https://example.com", delay=0)

    assert soup is None
    assert reason is not None
    assert reason.startswith("request failed"), (
        f"reason should start with 'request failed', got: {reason!r}"
    )
    assert mock_get.call_count == 3, f"expected 3 attempts, got {mock_get.call_count}"
    # delay=0 politeness + backoff 2s after attempt 0, 4s after attempt 1; no third backoff
    assert waits == [0, 2, 4], f"unexpected sleep sequence: {waits}"
