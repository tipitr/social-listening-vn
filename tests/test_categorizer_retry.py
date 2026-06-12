"""Fix: transient Claude API errors should be retried with backoff, and a
deterministically-failing batch must not refetch forever.

Today a 529 mid-run skips the batch with no retry; worse, `continue` refetches
the SAME rows (they're still NULL), so a batch that always fails loops forever.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import anthropic
import pytest


@pytest.fixture
def no_sleep(monkeypatch):
    """Capture backoff sleeps instead of actually waiting."""
    waits = []
    monkeypatch.setattr("pipeline.categorizer.time.sleep", lambda s: waits.append(s))
    return waits


def _fake_response(payload_obj):
    fake = MagicMock()
    fake.content = [MagicMock(text=json.dumps(payload_obj))]
    fake.usage = MagicMock(input_tokens=10, output_tokens=10)
    return fake


def _client(side_effects):
    client = MagicMock()
    client.messages.create.side_effect = side_effects
    return client


@pytest.fixture
def one_batch_db(monkeypatch):
    """A single batch of one article, then empty — tracks updates + cursor."""
    state = {"fetch_calls": [], "updated_ids": []}
    batch = [{"id": 1, "title": "Article", "summary": "x" * 30}]

    def fake_fetch(fetch_sql, batch_size, min_len, after):
        state["fetch_calls"].append(after)
        # Simulate the real cursor: row 1 only visible while after < 1
        # and while it hasn't been updated (stamped) yet.
        if after < 1 and 1 not in state["updated_ids"]:
            return list(batch)
        return []

    def fake_update(update_sql, results):
        state["updated_ids"].extend(r["id"] for r in results)
        return len(results)

    import pipeline.categorizer as cat
    monkeypatch.setattr(cat, "_fetch_batch", fake_fetch)
    monkeypatch.setattr(cat, "_update_batch", fake_update)
    monkeypatch.setattr(cat, "init_db", lambda: None)
    monkeypatch.setattr("pipeline.categorizer.log_usage", lambda *a, **k: None)
    return state


def test_transient_api_error_is_retried_then_succeeds(one_batch_db, no_sleep, monkeypatch):
    """529 twice, then success — the batch should end up categorized."""
    err = anthropic.APIError(message="Overloaded", request=MagicMock(), body=None)
    ok = _fake_response([{"id": 1, "sentiment": "neutral", "category": "general",
                          "intent": "seeking_info", "summary_vi": "a", "summary_en": "b"}])
    client = _client([err, err, ok])
    monkeypatch.setattr("anthropic.Anthropic", lambda **k: client)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    from pipeline import categorizer
    total = categorizer.run()

    assert total == 1, "batch should succeed on 3rd attempt"
    assert client.messages.create.call_count == 3
    assert no_sleep == [2, 4], "expected exponential backoff 2s then 4s"


def test_auth_error_is_never_retried(one_batch_db, no_sleep, monkeypatch):
    auth = anthropic.AuthenticationError(
        message="Invalid API key", response=MagicMock(status_code=401), body=None)
    client = _client([auth, _fake_response([])])
    monkeypatch.setattr("anthropic.Anthropic", lambda **k: client)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "bad-key")

    from pipeline import categorizer
    total = categorizer.run()

    assert total == 0
    assert client.messages.create.call_count == 1, "auth errors must not retry"
    assert no_sleep == []


def test_persistently_failing_batch_does_not_loop_forever(one_batch_db, no_sleep, monkeypatch):
    """Every attempt 529s — run() must terminate (cursor skips past the batch)."""
    def always_fail(**kwargs):
        raise anthropic.APIError(message="Overloaded", request=MagicMock(), body=None)
    client = MagicMock()
    client.messages.create.side_effect = always_fail
    monkeypatch.setattr("anthropic.Anthropic", lambda **k: client)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    from pipeline import categorizer
    total = categorizer.run()   # would hang forever before the fix

    assert total == 0
    # 3 attempts on the one batch, then the cursor moves past id=1 and the
    # next fetch returns [] → loop ends.
    assert client.messages.create.call_count == 3
    assert one_batch_db["fetch_calls"][-1] >= 1, "cursor should advance past the failed batch"
