"""TDD for fix #1: categorizer should survive transient errors mid-run.

ROOT CAUSE (from audit): pipeline/categorizer.py uses `break` on JSONDecodeError
and APIError, abandoning all remaining batches. Symptom: one transient 529 from
Claude → today's articles stay uncategorized for 24h until the next cron run.

EXPECTED BEHAVIOR after fix:
  - JSONDecodeError on batch N → log error, continue to batch N+1
  - anthropic.APIError on batch N → log error, continue to batch N+1
  - anthropic.AuthenticationError → break (not transient; user must fix key)

These tests run WITHOUT hitting Claude — we stub the client.
"""

from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import anthropic
import pytest


# ─── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def patched_db(monkeypatch):
    """Replace DB I/O with in-memory fakes.

    _fetch_batch is called once per loop iteration; we serve up two batches,
    then an empty list to terminate the while-True loop normally.
    """
    state = {
        "batches": [
            [{"id": 1, "title": "Batch 1 article", "summary": "x" * 30}],
            [{"id": 2, "title": "Batch 2 article", "summary": "y" * 30}],
            [],   # ← end of work
        ],
        "updated_ids": [],
    }

    def fake_fetch(batch_size, min_len):
        return state["batches"].pop(0)

    def fake_update(results):
        state["updated_ids"].extend(r["id"] for r in results)
        return len(results)

    import pipeline.categorizer as cat
    monkeypatch.setattr(cat, "_fetch_batch", fake_fetch)
    monkeypatch.setattr(cat, "_update_batch", fake_update)
    monkeypatch.setattr(cat, "init_db", lambda: None)
    # Don't try to log usage (would hit DB)
    monkeypatch.setattr("pipeline.categorizer.log_usage", lambda *a, **k: None)
    return state


def _mock_anthropic_client(side_effects):
    """Build an Anthropic client whose .messages.create returns the given
    side_effects list one item at a time.

    Each side_effect is either a raised exception or a fake response with
    `.content[0].text` and `.usage`.
    """
    client = MagicMock()
    client.messages.create.side_effect = side_effects
    return client


def _fake_response(payload_obj):
    """Build a fake Anthropic response whose .content[0].text is the JSON for payload_obj."""
    fake = MagicMock()
    fake.content = [MagicMock(text=json.dumps(payload_obj))]
    fake.usage = MagicMock(input_tokens=10, output_tokens=10)
    return fake


# ─── Tests ──────────────────────────────────────────────────────────────────

def test_categorizer_continues_after_jsondecode_error(patched_db, monkeypatch):
    """Batch 1 returns malformed JSON. Batch 2 should still be processed."""
    bad_response = MagicMock()
    bad_response.content = [MagicMock(text="this is not json {")]
    bad_response.usage = MagicMock(input_tokens=10, output_tokens=10)

    good_response = _fake_response([{
        "id": 2, "sentiment": "neutral", "category": "general",
        "intent": "seeking_info", "summary_vi": "x", "summary_en": "y",
    }])

    client = _mock_anthropic_client([bad_response, good_response])
    monkeypatch.setattr("anthropic.Anthropic", lambda **k: client)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    from pipeline import categorizer
    total = categorizer.run()

    # Batch 1 failed (0), batch 2 succeeded (1). Total = 1.
    assert total == 1, f"Expected 1 categorized article (batch 2), got {total}"
    assert patched_db["updated_ids"] == [2], "Only batch 2's id should be saved"


def test_categorizer_continues_after_api_error(patched_db, monkeypatch):
    """Batch 1 raises a transient APIError (e.g. 529). Batch 2 should still process."""
    api_error = anthropic.APIError(
        message="Overloaded", request=MagicMock(), body=None,
    )

    good_response = _fake_response([{
        "id": 2, "sentiment": "positive", "category": "promotion",
        "intent": "promotion", "summary_vi": "ưu đãi", "summary_en": "promo",
    }])

    client = _mock_anthropic_client([api_error, good_response])
    monkeypatch.setattr("anthropic.Anthropic", lambda **k: client)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    from pipeline import categorizer
    total = categorizer.run()

    assert total == 1, f"Expected batch 2 to succeed after batch 1's APIError, got {total}"
    assert patched_db["updated_ids"] == [2]


def test_categorizer_stops_on_authentication_error(patched_db, monkeypatch):
    """AuthError is NOT transient — bad key won't fix itself, stop the run."""
    auth_error = anthropic.AuthenticationError(
        message="Invalid API key", response=MagicMock(status_code=401), body=None,
    )

    # If we don't break, this would try batch 2 too — but we expect break here.
    client = _mock_anthropic_client([auth_error, _fake_response([])])
    monkeypatch.setattr("anthropic.Anthropic", lambda **k: client)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "bad-key")

    from pipeline import categorizer
    total = categorizer.run()

    assert total == 0
    # Critical: client.messages.create should have been called exactly ONCE
    # (we broke out of the loop after AuthError, didn't try batch 2).
    assert client.messages.create.call_count == 1, (
        "AuthError should stop the loop — but we kept calling the API"
    )
