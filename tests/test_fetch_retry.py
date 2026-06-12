"""Shared scraper fetch: transient HTTP failures retry with backoff; total
failure returns None (one dead site must not raise into the collector)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import requests


def _ok_response():
    resp = MagicMock()
    resp.text = "<html><body><p>ok</p></body></html>"
    resp.raise_for_status = MagicMock()
    return resp


def test_get_soup_retries_then_succeeds(monkeypatch):
    waits = []
    monkeypatch.setattr("scrapers.fetch.time.sleep", lambda s: waits.append(s))

    with patch("scrapers.fetch.requests.get") as mock_get:
        mock_get.side_effect = [
            requests.ConnectionError("boom"),
            requests.ConnectionError("boom"),
            _ok_response(),
        ]
        from scrapers.fetch import get_soup
        soup = get_soup("https://example.com", delay=1)

    assert soup is not None and soup.find("p").text == "ok"
    assert mock_get.call_count == 3
    # waits[0] is the politeness delay (1), then backoff 2s and 4s
    assert waits == [1, 2, 4]


def test_get_soup_returns_none_after_all_retries(monkeypatch):
    monkeypatch.setattr("scrapers.fetch.time.sleep", lambda s: None)

    with patch("scrapers.fetch.requests.get") as mock_get:
        mock_get.side_effect = requests.ConnectionError("dead site")
        from scrapers.fetch import get_soup
        soup = get_soup("https://example.com", delay=0)

    assert soup is None, "must degrade gracefully, never raise"
    assert mock_get.call_count == 3


def test_get_soup_always_sets_timeout():
    with patch("scrapers.fetch.requests.get") as mock_get:
        mock_get.return_value = _ok_response()
        from scrapers.fetch import get_soup
        get_soup("https://example.com", delay=0)
    assert mock_get.call_args.kwargs.get("timeout") == 15
