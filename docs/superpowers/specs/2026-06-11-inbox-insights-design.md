# Inbox Insights — Design

**Date:** 2026-06-11
**Status:** Approved (design), pending implementation

## Goal
Surface home-loan signal from KBank Vietnam's Facebook **page inbox** (private
Messenger chats): filter to home-loan messages, categorize them, and show
monthly volume/topic/sentiment trends in a new dashboard tab. Privacy-first:
personal info is masked before anything is stored.

## Privacy stance (decided)
- **Mask on ingest.** Strip phone numbers and emails from message text.
- **No customer names.** Drop the `from.name` field; identify a thread only by
  an anonymized `conversation_ref` (`chat#` + short hash of the FB conversation id).
- **Customer voice only.** Skip messages sent *by the page itself* (agent replies).
- **Separate table.** Private inbox data lives in its own `inbox_messages` table,
  never mixed into `articles`, so it can never leak into public bank-comparison views.

## Components

### 1. `scrapers/facebook_inbox.py`
- Reads `GET /{page_id}/conversations?fields=messages{id,message,created_time,from}`
  using the Page token already in `.env` (`FACEBOOK_ACCESS_TOKEN`).
- For each message: skip empty (attachments/stickers); skip if `from.id == page_id`;
  keep only home-loan-relevant (same keyword filter as `scrapers/facebook.py`);
  mask PII; convert timestamp to GMT+7 via `pipeline/timeutils`.
- Returns list of dicts: `fb_message_id`, `conversation_ref`, `message`, `sent_at`.

### 2. `inbox_messages` table (`pipeline/db.py`)
Columns: `id` PK, `fb_message_id` UNIQUE (dedup), `conversation_ref`, `message`,
`category`, `sentiment`, `intent`, `summary_vi`, `summary_en`, `sent_at`, `created_at`.
Index on `sent_at DESC`. Created in `init_schema()` (SQLite + Postgres).

### 3. Categorization (`pipeline/categorizer.py`)
Reuse the existing Claude call + `SYSTEM_PROMPT` + validation. Refactor the
batch core into a shared helper; add `run_inbox()` that reads uncategorized rows
from `inbox_messages` and writes back the same five fields. Same category set.

### 4. Collector wiring (`pipeline/collector.py`)
When the FB token is present, after scraping own-page posts: scrape inbox →
`save_messages()` (INSERT OR IGNORE on `fb_message_id`) → `categorizer.run_inbox()`.

### 5. Dashboard tab (`dashboard/app.py`)
New "💬 Inbox Insights" tab:
- Monthly trend — home-loan chat volume per month
- Category breakdown by month — what customers ask about
- Sentiment over time
- A sample of recent masked messages

## Out of scope (YAGNI)
- Replying to messages. Read-only.
- Full conversation threading/UI. We store individual relevant messages.
- Backfilling years of history — we read whatever the API returns; daily runs
  accumulate going forward, deduped by `fb_message_id`.
