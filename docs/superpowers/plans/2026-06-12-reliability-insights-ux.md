# Reliability + Insights + UX Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the pipeline survive transient failures without losing a day's data, stop paying Claude twice for the same article, gate the daily scrape on passing tests, then layer "so what" insights (deltas, spike notes, complaint themes) and UX polish (persistent dismissals, theme consolidation, mobile) onto the dashboard.

**Architecture:** Three phases. Phase A hardens `pipeline/categorizer.py` (retry + `categorized_at` stamp + cursor-based batch progress), adds a shared HTTP-retry helper for the BS4 scrapers, and makes `main.py` + the GitHub workflow fail loudly. Phase B adds delta captions, trend-chart annotations, and a complaint-theme panel to the Analytics tab (reusing `wordcloud_view`'s phrase extraction — zero new API cost). Phase C persists dismissed articles via the existing `reports` table, centralizes chart layout in `theme.py`, and fixes mobile breakpoints.

**Tech Stack:** Python 3.9 (no `X | None` syntax), pytest, SQLite/Postgres dual backend via `pipeline/db.py`, Streamlit + Plotly, GitHub Actions.

**Project rules that bind every task:** timestamps via `pipeline/timeutils.now_iso()` (never `datetime.now()/utcnow()`), no hardcoded keywords/URLs, log-don't-crash, one scraper failing must not stop others, UTF-8 Vietnamese text.

---

## Phase A — Reliability

### Task 1: Claude API retry with backoff + batch cursor (no more lost/looping batches)

**Files:**
- Modify: `pipeline/categorizer.py`
- Test: `tests/test_categorizer_retry.py` (new), `tests/test_categorizer_resilience.py` (update fake fetch signature)

Behavior changes:
1. Transient `anthropic.APIError` → retry up to 3 attempts with 2s/4s backoff (`AuthenticationError` still stops immediately — it's a subclass of `APIError`, so it must be caught/re-raised first).
2. `max_tokens` 2048 → 4096 (truncation headroom; output is paid per token actually generated, so no cost increase on normal batches).
3. Fetch query gains `AND id > :after` cursor. On a batch that fails after retries, advance `after` past that batch so the run continues with the NEXT articles instead of refetching the same failing batch forever (today's `continue` refetches the identical batch → infinite loop on deterministic failures). Failed rows keep `sentiment IS NULL` and are retried on the next run.

- [ ] **Step 1: Update the fake fetch in `tests/test_categorizer_resilience.py` to the new 3-arg signature**

In `patched_db` fixture, replace:

```python
    def fake_fetch(batch_size, min_len):
        return state["batches"].pop(0)
```

with:

```python
    def fake_fetch(batch_size, min_len, after):
        return state["batches"].pop(0)
```

(The monkeypatch target is `cat._fetch_batch`, which Task 1 changes to accept `after`.)

- [ ] **Step 2: Write the failing tests** — create `tests/test_categorizer_retry.py`:

```python
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

    def fake_fetch(batch_size, min_len, after):
        state["fetch_calls"].append(after)
        # Simulate the real cursor: row 1 only visible while after < 1
        # and while it hasn't been updated (stamped) yet.
        if after < 1 and 1 not in state["updated_ids"]:
            return list(batch)
        return []

    def fake_update(results):
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
```

- [ ] **Step 3: Run the new tests to verify they fail**

Run: `python3 -m pytest tests/test_categorizer_retry.py -v`
Expected: FAIL (TypeError on `_fetch_batch` signature / no retry behavior / hang-protection assertion).
Note: the loop test would hang on current code if run as-is — the fixture's `fetch_calls` cursor simulation still returns the same batch when `after` never advances, but `side_effect=always_fail` + current `continue` → infinite loop. **Run this step with a timeout:** `python3 -m pytest tests/test_categorizer_retry.py -v --timeout=10` if `pytest-timeout` is available, otherwise expect to Ctrl-C / kill after a few seconds and treat the hang as the failing evidence.

- [ ] **Step 4: Implement in `pipeline/categorizer.py`**

Add `time` to imports (top of file):

```python
import time
```

Replace `_FETCH_UNCATEGORIZED` and `_FETCH_UNCAT_INBOX` to include the cursor:

```python
_FETCH_UNCATEGORIZED = """
    SELECT id, title, summary
    FROM articles
    WHERE (sentiment IS NULL OR summary_en IS NULL)
      AND id > :after
      AND length(COALESCE(title, '') || COALESCE(summary, '')) >= :min_len
    ORDER BY id
    LIMIT :batch_size;
"""
```

```python
_FETCH_UNCAT_INBOX = """
    SELECT id, message
    FROM inbox_messages
    WHERE (topic IS NULL OR summary_en IS NULL)
      AND id > :after
      AND length(COALESCE(message, '')) >= :min_len
    ORDER BY id
    LIMIT :batch_size;
"""
```

Update `_fetch_batch`:

```python
def _fetch_batch(fetch_sql: str, batch_size: int, min_len: int, after: int) -> list[dict]:
    with db.connect() as conn:
        rows = conn.execute(
            fetch_sql,
            {"batch_size": batch_size, "min_len": min_len, "after": after},
        ).fetchall()
    return [dict(r) for r in rows]
```

Add the retry helper (below `_build_user_message`):

```python
_MAX_ATTEMPTS = 3


def _call_with_retry(client, **kwargs):
    """Call Claude, retrying transient API errors with 2s/4s backoff.

    AuthenticationError re-raises immediately (a bad key won't fix itself —
    it's an APIError subclass, so it must be caught first). After the final
    attempt the APIError propagates so the caller's skip-batch handling runs.
    """
    for attempt in range(_MAX_ATTEMPTS):
        try:
            return client.messages.create(**kwargs)
        except anthropic.AuthenticationError:
            raise
        except anthropic.APIError as exc:
            if attempt == _MAX_ATTEMPTS - 1:
                raise
            wait = 2 * (2 ** attempt)   # 2s, 4s
            logger.warning("Claude API error (attempt %d/%d), retrying in %ds: %s",
                           attempt + 1, _MAX_ATTEMPTS, wait, exc)
            time.sleep(wait)
```

Rewrite the `while True` loop body in `_categorize` (the `after` cursor replaces blind refetching; `max_tokens` bumped):

```python
    total_categorized = 0
    after = 0   # id cursor — advances past failed batches so a bad batch
                # can't be refetched forever within one run

    while True:
        batch = _fetch_batch(fetch_sql, batch_size, min_len, after)
        if not batch:
            break

        logger.info("Processing batch of %d %s (ids %d–%d)",
                    len(batch), label, batch[0]["id"], batch[-1]["id"])
        try:
            response = _call_with_retry(
                client,
                model=MODEL,
                max_tokens=4096,
                system=[
                    {
                        "type": "text",
                        "text": system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user",
                           "content": _build_user_message([to_item(r) for r in batch])}],
            )
            raw = response.content[0].text
            parsed = _extract_json(raw)
            validated = [validate_fn(item) for item in parsed]
            saved = _update_batch(update_sql, validated)
            total_categorized += saved
            logger.info("  → categorized %d %s", saved, label)

            # Log token usage — Sonnet 4.6: $3/$15 per 1M in/out
            u = response.usage
            cost = (u.input_tokens / 1_000_000 * 3) + (u.output_tokens / 1_000_000 * 15)
            log_usage("claude_categorizer", MODEL, u.input_tokens, u.output_tokens, cost, saved)

        except json.JSONDecodeError as exc:
            # Claude occasionally returns half-truncated JSON. Skip PAST this
            # batch (cursor) so the rest of the day's items still get labeled;
            # the skipped rows stay NULL and are retried on the next run.
            logger.error("Failed to parse JSON response for batch (skipping past it): %s", exc)
            after = batch[-1]["id"]
            continue
        except anthropic.AuthenticationError as exc:
            # NOT transient — a bad key won't fix itself, no point looping.
            logger.error("Authentication failed — check ANTHROPIC_API_KEY: %s", exc)
            break
        except anthropic.APIError as exc:
            # Already retried 3x inside _call_with_retry. Move past the batch.
            logger.error("Claude API error for batch after retries (skipping past it): %s", exc)
            after = batch[-1]["id"]
            continue
```

- [ ] **Step 5: Run the full categorizer test suite**

Run: `python3 -m pytest tests/test_categorizer_retry.py tests/test_categorizer_resilience.py -v`
Expected: ALL PASS. (The resilience tests' semantics still hold: bad batch 1 → batch 2 still processed, because the fake fetch pops batches.)

- [ ] **Step 6: Commit**

```bash
git add pipeline/categorizer.py tests/test_categorizer_retry.py tests/test_categorizer_resilience.py
git commit -m "Retry transient Claude errors with backoff; cursor past failed batches"
```

---

### Task 2: `categorized_at` stamp — never pay Claude twice for the same article

**Files:**
- Modify: `pipeline/db.py` (migration + backfill), `pipeline/categorizer.py` (stamp on write)
- Test: `tests/test_categorized_at.py` (new)

Design: new nullable TEXT column `categorized_at` on `articles` AND `inbox_messages`. The UPDATE statements stamp it with `now_iso()`. Migration backfills `categorized_at = created_at` for rows already labeled, so the first run after deploy doesn't re-pay for history. The FETCH queries keep their existing NULL-label predicates (so rows skipped by a failed batch are still retried next run) — the stamp's job is idempotency bookkeeping + a staleness metric, not the fetch filter.

- [ ] **Step 1: Write the failing test** — create `tests/test_categorized_at.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_categorized_at.py -v`
Expected: FAIL (no such column `categorized_at`; KeyError on `categorized_at`).

- [ ] **Step 3: Implement the migration in `pipeline/db.py`**

Extend `_MIGRATION_COLS`:

```python
_MIGRATION_COLS = {
    "sentiment":      "TEXT",
    "intent":         "TEXT",
    "summary_vi":     "TEXT",
    "summary_en":     "TEXT",
    "categorized_at": "TEXT",
}
```

In `init_schema()`, after the existing `topic` migration for inbox, add `categorized_at` to `inbox_messages` and the backfill. Postgres branch:

```python
            conn.execute("ALTER TABLE inbox_messages ADD COLUMN IF NOT EXISTS topic TEXT")
            conn.execute("ALTER TABLE inbox_messages ADD COLUMN IF NOT EXISTS categorized_at TEXT")
```

SQLite branch:

```python
            if "topic" not in inbox_cols:
                conn.execute("ALTER TABLE inbox_messages ADD COLUMN topic TEXT")
            if "categorized_at" not in inbox_cols:
                conn.execute("ALTER TABLE inbox_messages ADD COLUMN categorized_at TEXT")
```

Then, after both branches (still inside the `with connect() as conn:` block, before the index creation), the backfill — plain UPDATEs that run on both backends:

```python
        # Backfill: rows labeled before the categorized_at column existed get
        # stamped from created_at, so the next run doesn't re-pay Claude for
        # the entire history.
        conn.execute(
            "UPDATE articles SET categorized_at = created_at "
            "WHERE categorized_at IS NULL "
            "  AND sentiment IS NOT NULL AND summary_en IS NOT NULL"
        )
        conn.execute(
            "UPDATE inbox_messages SET categorized_at = created_at "
            "WHERE categorized_at IS NULL "
            "  AND topic IS NOT NULL AND summary_en IS NOT NULL"
        )
```

- [ ] **Step 4: Stamp on write in `pipeline/categorizer.py`**

Add import at top:

```python
from pipeline.timeutils import now_iso
```

Update both UPDATE statements:

```python
_UPDATE_ARTICLE = """
    UPDATE articles
    SET sentiment      = :sentiment,
        category       = :category,
        intent         = :intent,
        summary_vi     = :summary_vi,
        summary_en     = :summary_en,
        categorized_at = :categorized_at
    WHERE id = :id;
"""
```

```python
_UPDATE_INBOX = """
    UPDATE inbox_messages
    SET topic          = :topic,
        sentiment      = :sentiment,
        summary_vi     = :summary_vi,
        summary_en     = :summary_en,
        categorized_at = :categorized_at
    WHERE id = :id;
"""
```

Add the stamp to both validators (`_validate` and `_validate_inbox` return dicts — add one key to each):

```python
        "categorized_at": now_iso(),
```

- [ ] **Step 5: Run tests**

Run: `python3 -m pytest tests/test_categorized_at.py tests/test_categorizer_retry.py tests/test_categorizer_resilience.py -v`
Expected: ALL PASS.

- [ ] **Step 6: Commit**

```bash
git add pipeline/db.py pipeline/categorizer.py tests/test_categorized_at.py
git commit -m "Stamp categorized_at on labeled rows + backfill history"
```

---

### Task 3: HTTP retry for the BS4 scrapers (news, forums, smart_scraper)

**Files:**
- Create: `scrapers/fetch.py`
- Modify: `scrapers/news.py`, `scrapers/forums.py`, `scrapers/smart_scraper.py` (delegate their `_get_soup` to the shared helper — check smart_scraper's actual fetch function name when editing; it may differ)
- Test: `tests/test_fetch_retry.py` (new)

- [ ] **Step 1: Write the failing test** — create `tests/test_fetch_retry.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_fetch_retry.py -v`
Expected: FAIL — `ModuleNotFoundError: scrapers.fetch`.

- [ ] **Step 3: Create `scrapers/fetch.py`**

```python
"""Shared HTTP fetch for the BeautifulSoup scrapers — retry with backoff.

Vietnamese news sites and forums drop requests intermittently (CDN hiccups,
brief 503s). Before this helper, one failed GET silently cost a whole day of
articles from that site. Three attempts with 2s/4s backoff ride out the
typical blip; total failure still returns None so one dead site never stops
the other scrapers (project rule: log, don't crash).
"""

import logging
import time

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8",
}

_MAX_ATTEMPTS = 3


def get_soup(url, delay=0, headers=None, max_attempts=_MAX_ATTEMPTS):
    """Polite fetch: wait `delay`s, then GET with retries. None on failure."""
    time.sleep(delay)
    for attempt in range(max_attempts):
        try:
            resp = requests.get(url, headers=headers or DEFAULT_HEADERS, timeout=15)
            resp.encoding = "utf-8"
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "lxml")
        except Exception as exc:
            if attempt == max_attempts - 1:
                logger.warning("Failed to fetch %s after %d attempts: %s",
                               url, max_attempts, exc)
                return None
            wait = 2 * (2 ** attempt)   # 2s, 4s
            logger.info("Fetch failed for %s (attempt %d/%d), retrying in %ds: %s",
                        url, attempt + 1, max_attempts, wait, exc)
            time.sleep(wait)
    return None
```

- [ ] **Step 4: Delegate in `scrapers/news.py` and `scrapers/forums.py`**

In BOTH files, replace the `_get_soup` body (keep the name — parsers call it):

```python
from scrapers.fetch import get_soup as _shared_get_soup


def _get_soup(url, delay):
    return _shared_get_soup(url, delay, headers=HEADERS)
```

(Keep each file's `HEADERS` — the Accept-Language header matters for Vietnamese content. Remove the now-unused `import time` / `import requests` / `BeautifulSoup` import ONLY if nothing else in the file uses them — check with grep before deleting.)

In `scrapers/smart_scraper.py`: find its requests-based fetch function (~line 68–82) and delegate the same way. If its fetch returns something other than soup (e.g. raw text), adapt minimally or leave it and add retry inline with the same 2s/4s pattern — match whatever shape it already has.

- [ ] **Step 5: Run the full suite (timeouts test guards the `timeout=` contract)**

Run: `python3 -m pytest tests/ -v`
Expected: ALL PASS, including `tests/test_timeouts.py`. If `test_timeouts.py` scans specific files for `timeout=`, add `scrapers/fetch.py` to its scan list.

- [ ] **Step 6: Commit**

```bash
git add scrapers/fetch.py scrapers/news.py scrapers/forums.py scrapers/smart_scraper.py tests/test_fetch_retry.py
git commit -m "Retry transient HTTP failures in news/forum scrapers (2s/4s backoff)"
```

---

### Task 4: Fail loudly + CI test gate

**Files:**
- Modify: `main.py`, `.github/workflows/daily_scrape.yml`
- No new tests (workflow YAML isn't unit-testable here; main.py change is 6 lines of orchestration)

- [ ] **Step 1: Make `main.py` exit non-zero on total failure**

Replace the `if __name__ == "__main__":` block:

```python
if __name__ == "__main__":
    logger.info("=== Pipeline starting ===")

    try:
        inserted = collect_all()
        logger.info("Collected %d new articles", inserted)

        if inserted == 0:
            # collect_all only categorizes when new rows landed — sweep up stragglers
            categorize()
    except Exception:
        # Individual scraper failures are already swallowed inside collect_all;
        # reaching here means the PIPELINE itself died (DB down, bad config).
        # Exit non-zero so the GitHub Actions run shows a red ✗ instead of a
        # green check over a silent failure.
        logger.exception("Pipeline failed")
        sys.exit(1)

    logger.info("=== Pipeline complete ===")
```

(`sys` is already imported at the top of main.py.)

- [ ] **Step 2: Add the test job to `.github/workflows/daily_scrape.yml`**

Replace the `jobs:` section header area so the file reads:

```yaml
jobs:
  # Run the test suite first — a broken keyword filter or categorizer bug
  # should fail HERE, not silently corrupt a day's data in production.
  test:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - name: Check out the code
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install pytest

      - name: Run tests
        run: pytest -q

  scrape:
    needs: test
    runs-on: ubuntu-latest
    timeout-minutes: 30
    ... (existing steps unchanged)
```

(If `pytest` is already in `requirements.txt`, drop the extra `pip install pytest` line.)

- [ ] **Step 3: Verify locally**

Run: `python3 -m pytest -q` (full suite green) and `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/daily_scrape.yml'))"` (YAML parses).
Expected: tests pass; no YAML error.

- [ ] **Step 4: Commit**

```bash
git add main.py .github/workflows/daily_scrape.yml
git commit -m "Fail loudly on pipeline crash; gate daily scrape on passing tests"
```

---

## Phase B — Insight upgrades

### Task 5: "So what" delta captions on the Analytics charts

**Files:**
- Modify: `dashboard/app.py` (tab_overview, ~line 1947–2005)

`df_prev` (previous N-day window) is already loaded at module level (line ~1260) and is in scope inside the tab. Each chart gets a one-line takeaway above it.

- [ ] **Step 1: Add the takeaway helper + captions in `tab_overview`**

Immediately after the "Composition · …" kicker `st.html(...)` (line ~1958), add:

```python
    # ── "So what" takeaways — every chart leads with the conclusion ──────
    def _takeaway(text: str, tone: str = "neutral") -> str:
        color = {"good": "#22C55E", "bad": "#F87171", "neutral": "#94A3B8"}[tone]
        return (f'<div style="font-family:\'IBM Plex Sans\',sans-serif;'
                f'font-size:0.82rem;color:{color};margin:-6px 0 6px">{text}</div>')

    _has_prev = not df_prev.empty
```

Inside `with c1:` (Sentiment pie), after `st.subheader("Sentiment")`:

```python
        _neg_now = (df["sentiment"] == "negative").mean() * 100
        if _has_prev:
            _neg_prev = (df_prev["sentiment"] == "negative").mean() * 100
            _pp = _neg_now - _neg_prev
            _arrow = "▲" if _pp > 0 else ("▼" if _pp < 0 else "→")
            _tone = "bad" if _pp > 2 else ("good" if _pp < -2 else "neutral")
            st.html(_takeaway(
                f"Negative voices: {_neg_now:.0f}% of the conversation "
                f"({_arrow} {abs(_pp):.0f}pp vs previous {days}d)", _tone))
        else:
            st.html(_takeaway(f"Negative voices: {_neg_now:.0f}% of the conversation"))
```

Inside `with c2:` (Category bar), after `st.subheader("Category")`:

```python
        _comp_now = int((df["category"] == "complaint").sum())
        if _has_prev:
            _comp_prev = int((df_prev["category"] == "complaint").sum())
            _diff = _comp_now - _comp_prev
            _tone = "bad" if _diff > 0 else ("good" if _diff < 0 else "neutral")
            _sign = "+" if _diff > 0 else ""
            st.html(_takeaway(
                f"Complaints: {_comp_now} this window ({_sign}{_diff} vs previous {days}d)", _tone))
        else:
            st.html(_takeaway(f"Complaints: {_comp_now} this window"))
```

Inside `with c3:` (Intent bar), after `st.subheader("Intent")`:

```python
        _seek_now = (df["intent"] == "seeking_info").mean() * 100
        st.html(_takeaway(
            f"{_seek_now:.0f}% of posts are people actively ASKING about loans "
            f"— each one is a potential lead", "good" if _seek_now >= 30 else "neutral"))
```

- [ ] **Step 2: Visual check**

Run: `streamlit run dashboard/app.py` briefly (or rely on Step 3 of Task 7's combined check) — captions render above the three charts, colors match tone.

- [ ] **Step 3: Commit**

```bash
git add dashboard/app.py
git commit -m "Lead each Analytics chart with a delta takeaway, not just raw shape"
```

---

### Task 6: Spike annotations on the daily trend chart

**Files:**
- Modify: `dashboard/app.py` (trend chart, ~line 2043–2058)

- [ ] **Step 1: Annotate peak day + biggest jump**

After the existing `fig.update_layout(...)` of the "Volume by day" chart and before `st.plotly_chart(fig, use_container_width=True)`, add:

```python
    # Spike callouts — label the peak day and the sharpest day-over-day rise
    # so the reader doesn't have to eyeball "what changed".
    _daily_tot = (vol_df.groupby(vol_df["scraped_at"].dt.date).size()
                  .sort_index())
    if len(_daily_tot) >= 2:
        _peak_day = _daily_tot.idxmax()
        _peak_val = int(_daily_tot.max())
        fig.add_annotation(
            x=_peak_day.strftime("%d %b"), y=_peak_val,
            text=f"Peak · {_peak_val}", showarrow=True, arrowhead=2,
            arrowcolor="#22C55E", ax=0, ay=-28,
            font=dict(size=11, color="#22C55E", family="IBM Plex Mono, monospace"),
        )
        _jumps = _daily_tot.diff()
        _jump_day = _jumps.idxmax()
        _jump_val = _jumps.max()
        # Only call out a jump that is both meaningful (≥3) and not the peak
        # we already labeled.
        if pd.notna(_jump_val) and _jump_val >= 3 and _jump_day != _peak_day:
            fig.add_annotation(
                x=_jump_day.strftime("%d %b"), y=int(_daily_tot[_jump_day]),
                text=f"+{int(_jump_val)} vs day before", showarrow=True, arrowhead=2,
                arrowcolor="#F59E0B", ax=0, ay=-24,
                font=dict(size=10, color="#F59E0B", family="IBM Plex Mono, monospace"),
            )
```

- [ ] **Step 2: Commit**

```bash
git add dashboard/app.py
git commit -m "Annotate trend chart with peak day and sharpest rise"
```

---

### Task 7: Complaint-theme ranking (clustering without API cost)

**Files:**
- Modify: `dashboard/wordcloud_view.py` (add `top_phrases`), `dashboard/app.py` (panel in tab_overview)
- Test: `tests/test_top_phrases.py` (new)

- [ ] **Step 1: Write the failing test** — create `tests/test_top_phrases.py`:

```python
"""top_phrases: rank recurring bigrams for the complaint-theme panel."""

from __future__ import annotations

from dashboard.wordcloud_view import top_phrases


def test_recurring_bigrams_ranked_first():
    texts = [
        "giải ngân chậm quá",
        "giải ngân chậm thật sự",
        "giải ngân chậm rồi",
        "hồ sơ phức tạp",
        "hồ sơ phức tạp ghê",
    ]
    result = top_phrases(texts, home_loan_cfg={}, k=3)
    phrases = [p for p, _ in result]
    assert phrases[0] == "giải ngân chậm" or phrases[0] == "ngân chậm" or "giải ngân" in phrases[0]
    counts = [c for _, c in result]
    assert counts == sorted(counts, reverse=True), "must be ranked by count desc"


def test_one_off_phrases_are_dropped():
    texts = ["lãi suất tăng", "phí phạt cao"]   # each bigram appears once
    assert top_phrases(texts, home_loan_cfg={}, k=5) == []


def test_blocked_generic_phrases_excluded():
    # "vay mua" is in the generic blocklist — must never surface as a theme
    texts = ["vay mua nhà"] * 5
    phrases = [p for p, _ in top_phrases(texts, home_loan_cfg={}, k=5)]
    assert "vay mua" not in phrases
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_top_phrases.py -v`
Expected: FAIL — `ImportError: cannot import name 'top_phrases'`.

- [ ] **Step 3: Implement `top_phrases` in `dashboard/wordcloud_view.py`**

Add at the end of the file:

```python
def top_phrases(
    texts: Iterable[str],
    home_loan_cfg: dict,
    k: int = 6,
) -> "list[tuple[str, int]]":
    """Top recurring bigrams — powers the complaint-theme ranking.

    Bigrams only (single words read as noise in a theme list), minimum two
    occurrences (a theme is something people keep saying), same blocklist as
    the word cloud so generic home-loan vocabulary never surfaces as a theme.
    """
    blocklist = _build_blocklist(home_loan_cfg)
    freq = _extract_phrases(texts, blocklist)
    bigrams = Counter({p: c for p, c in freq.items() if " " in p and c >= 2})
    return bigrams.most_common(k)
```

- [ ] **Step 4: Run the test**

Run: `python3 -m pytest tests/test_top_phrases.py -v`
Expected: PASS.

- [ ] **Step 5: Add the panel to `tab_overview` in `dashboard/app.py`**

After the trend chart block (after its `st.plotly_chart(fig, use_container_width=True)`), add:

```python
    # ── Top complaint themes ──────────────────────────────────────────────
    # 15 separate complaint cards hide the fact that 12 of them say the same
    # thing. Rank the recurring phrases so the #1 pain point is undeniable.
    st.html(
        '<div style="font-family:\'IBM Plex Mono\',monospace;font-size:0.7rem;'
        'color:#64748B;letter-spacing:0.08em;text-transform:uppercase;'
        'margin:24px 0 8px">Pain points · What complaints keep repeating</div>'
    )
    _pain_df = df[(df["category"] == "complaint") | (df["sentiment"] == "negative")]
    _pain_texts = (
        _pain_df["title"].fillna("") + " " + _pain_df.get("summary_vi", pd.Series(dtype=str)).fillna("")
    ).tolist() if not _pain_df.empty else []

    from dashboard.wordcloud_view import top_phrases as _top_phrases
    _themes = _top_phrases(_pain_texts, keywords_cfg.get("home_loan", {})) if _pain_texts else []

    if not _themes:
        st.caption("No recurring complaint themes in this window — nothing is "
                   "repeating often enough to stand out. That's a good sign.")
    else:
        _max_c = _themes[0][1]
        _rows = []
        for _i, (_phrase, _count) in enumerate(_themes, start=1):
            _w = max(8, int(_count / _max_c * 100))
            _rows.append(
                f'<div style="display:flex;align-items:center;gap:12px;margin:6px 0">'
                f'  <span style="font-family:\'IBM Plex Mono\',monospace;font-size:0.72rem;'
                f'color:#64748B;width:22px">#{_i}</span>'
                f'  <span style="font-family:\'IBM Plex Sans\',sans-serif;font-size:0.9rem;'
                f'color:#F8FAFC;min-width:200px">{_phrase}</span>'
                f'  <div style="flex:1;max-width:420px;background:#0F172A;border-radius:4px;height:10px">'
                f'    <div style="width:{_w}%;background:rgba(239,68,68,0.55);height:10px;'
                f'border-radius:4px"></div>'
                f'  </div>'
                f'  <span style="font-family:\'IBM Plex Mono\',monospace;font-size:0.75rem;'
                f'color:#94A3B8">{_count}×</span>'
                f'</div>'
            )
        st.html('<div style="margin:0 0 8px">' + "".join(_rows) + "</div>")
```

NOTE: `keywords_cfg` — check what name app.py uses for the loaded keywords config (grep `load_keywords` in app.py). If it loads keywords under a different variable (or only inside the word-cloud section), reuse that variable or call `load_keywords().get("home_loan", {})` directly with the cached loader app.py already uses.

- [ ] **Step 6: Run full tests + visual check, then commit**

Run: `python3 -m pytest -q`
Expected: ALL PASS.

```bash
git add dashboard/wordcloud_view.py dashboard/app.py tests/test_top_phrases.py
git commit -m "Rank recurring complaint themes so the top pain point is explicit"
```

---

## Phase C — UX polish

### Task 8: Dismissed articles survive refresh (persist to the reports table)

**Files:**
- Modify: `dashboard/app.py` (lines ~1447–1448 init; ~1677, ~1682, ~1729 mutations)

Uses the existing `reports` key-value table via `db.save_report`/`db.get_report` — no new table, works on both backends. Single shared list (the dashboard has no per-user auth; the team triages as one queue).

- [ ] **Step 1: Load persisted dismissals on session start**

Replace lines ~1447–1448:

```python
    if "dismissed_ids" not in st.session_state:
        # Dismissals are write-through to the shared reports table so "Done"
        # survives a refresh — and teammates see the same triaged queue.
        try:
            import json as _json
            from pipeline.db import get_report as _get_report
            _saved = _get_report("dismissed_article_ids")
            st.session_state["dismissed_ids"] = set(_json.loads(_saved)) if _saved else set()
        except Exception:
            st.session_state["dismissed_ids"] = set()
```

- [ ] **Step 2: Add the write-through helper right below**

```python
    def _persist_dismissed() -> None:
        """Best-effort write-through; the dashboard must render even if it fails."""
        try:
            import json as _json
            from pipeline.db import save_report as _save_report
            ids = sorted(st.session_state["dismissed_ids"])[-5000:]   # cap growth
            _save_report("dismissed_article_ids", _json.dumps(ids))
        except Exception:
            pass
```

- [ ] **Step 3: Call it at all three mutation sites**

"Dismiss all" button (~line 1677):

```python
                for _id in df_q["id"].tolist():
                    st.session_state["dismissed_ids"].add(_id)
                _persist_dismissed()
                st.rerun()
```

"Restore" button (~line 1682):

```python
                    st.session_state["dismissed_ids"] = set()
                    _persist_dismissed()
                    st.rerun()
```

Per-card "Done" button (~line 1729):

```python
                            st.session_state["dismissed_ids"].add(row["id"])
                            _persist_dismissed()
                            st.rerun()
```

- [ ] **Step 4: Run tests + commit**

Run: `python3 -m pytest -q` → ALL PASS.

```bash
git add dashboard/app.py
git commit -m "Persist dismissed articles so Done survives refresh"
```

---

### Task 9: One chart template + band colors from THEME

**Files:**
- Modify: `dashboard/theme.py`, `dashboard/app.py`

- [ ] **Step 1: Add layout tokens to `dashboard/theme.py`** (end of file):

```python
# ── Plotly layout tokens ────────────────────────────────────────────────────
# One margin + one legend position for every dashboard chart, so legends stop
# drifting ±0.1 between charts. Charts spread these, then override only what
# they genuinely need.
CHART_LAYOUT: dict = {
    "margin": {"t": 16, "b": 16, "l": 0, "r": 0},
    "xaxis_title": None,
    "yaxis_title": None,
}

CHART_LEGEND_H: dict = {"orientation": "h", "y": -0.25, "x": 0}
```

- [ ] **Step 2: Apply in `dashboard/app.py`'s Analytics charts**

Import alongside the existing theme import (find `from dashboard.theme import` near the top and extend it):

```python
from dashboard.theme import THEME, SENT_COLOR, CAT_COLOR, CHART_LAYOUT, CHART_LEGEND_H
```

(Match the actual existing import line — extend it, don't duplicate it.)

Then replace the per-chart layout calls in tab_overview:

Sentiment pie (~1970): `fig.update_layout(showlegend=False, **CHART_LAYOUT)`
Category bar (~1979): `fig.update_layout(showlegend=False, **CHART_LAYOUT)`
Intent bar (~1992): `fig.update_layout(showlegend=False, **CHART_LAYOUT)`
Source×Sentiment (~2002): `fig.update_layout(legend=CHART_LEGEND_H, **CHART_LAYOUT)`
Source-type bar (~2033): `fig_st.update_layout(showlegend=False, **CHART_LAYOUT)`
Volume-by-day (~2052): keep its `yaxis=dict(tickformat="d", dtick=1)` extra:

```python
    fig.update_layout(
        yaxis=dict(tickformat="d", dtick=1),
        legend=CHART_LEGEND_H,
        **CHART_LAYOUT,
    )
```

CAUTION: `**CHART_LAYOUT` and an explicit `margin=`/`xaxis_title=` in the same call would be a duplicate-kwarg error — remove the explicit ones when spreading.

- [ ] **Step 3: Band colors from THEME (~line 1701)**

```python
            _BAND_META = {
                "URGENT":  ("Things that look bad. Triage first.",
                            THEME["dark"]["danger"]),
                "WATCH":   ("Worth a glance — rate signals, competitor moves.",
                            THEME["dark"]["warning"]),
                "ROUTINE": ("Background chatter — read if you have time.",
                            THEME["dark"]["text_subtle"]),
            }
```

- [ ] **Step 4: Run tests + commit**

Run: `python3 -m pytest -q` → ALL PASS. Quick visual check that charts render with even margins.

```bash
git add dashboard/theme.py dashboard/app.py
git commit -m "Single chart layout template; band colors read from THEME"
```

---

### Task 10: Mobile breakpoints for the KPI grid

**Files:**
- Modify: `dashboard/app.py` (CSS block, ~line 142)

- [ ] **Step 1: Add phone-size breakpoints**

After the existing `@media (max-width: 1100px)` rule (~line 142–144), add:

```css
      @media (max-width: 768px) {
        .kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
        .kpi-spark { display: none; }     /* sparklines are unreadable this small */
        .kpi-tile { min-height: 64px; padding: 10px 12px; }
        .kpi-value { font-size: 1.45rem; }
      }
      @media (max-width: 480px) {
        .kpi-grid { grid-template-columns: 1fr; }
      }
```

- [ ] **Step 2: Run tests + commit**

Run: `python3 -m pytest -q` → ALL PASS.

```bash
git add dashboard/app.py
git commit -m "Readable KPI tiles on phones: stack grid, hide micro-sparklines"
```

---

## Final verification (after all tasks)

- [ ] `python3 -m pytest -q` — entire suite green
- [ ] `python3 -m py_compile pipeline/categorizer.py pipeline/db.py scrapers/fetch.py scrapers/news.py scrapers/forums.py scrapers/smart_scraper.py dashboard/app.py dashboard/theme.py dashboard/wordcloud_view.py main.py`
- [ ] `streamlit run dashboard/app.py` — visual smoke check: hero renders, Analytics tab shows takeaway captions + annotated trend + pain-point panel, Daily Brief "Done" persists across a browser refresh
- [ ] `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/daily_scrape.yml'))"`

## Self-review notes

- Spec coverage: fix 1 (retries) → Tasks 1+3; fix 2 (stamp) → Task 2; fix 3 (alerting, descoped to fail-loud per user) → Task 4; fix 4 (CI gate) → Task 4; deltas → Task 5; spike notes → Task 6; complaint grouping → Task 7; persistent dismissals → Task 8; theme/chart consistency → Task 9; mobile → Task 10. ✓
- Known judgment calls flagged inline: smart_scraper fetch-function name (Task 3 Step 4), keywords variable name in app.py (Task 7 Step 5), existing theme import line shape (Task 9 Step 2). The implementer must check those at edit time — grep first, then edit.
- Types consistent: `_fetch_batch(fetch_sql, batch_size, min_len, after)` matches all callers and both test fakes; `top_phrases(texts, home_loan_cfg, k)` matches both call sites.
