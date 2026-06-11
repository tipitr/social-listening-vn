"""Facebook Page **inbox** reader — home-loan signal from private Messenger chats.

Why this is separate from scrapers/facebook.py:
    facebook.py reads the page's *public* posts and comments. This module reads
    the *private* Messenger inbox (``/{page-id}/conversations``), which needs the
    ``pages_messaging`` permission on the Page access token.

Two modes:
    • ``scrape()``           — light daily run: recent conversations only.
    • ``scrape(deep=True)``  — block-by-block backfill: walks every conversation
      active within the lookback window and pages *into* long threads, so a
      home-loan question buried deep in a 1,000-message thread is still found.
      Facebook caps how much you can pull per call, so everything is fetched in
      small 50-item blocks with automatic back-off on rate limits.

Privacy is enforced here, at the point of ingest — nothing personal is ever
returned to the caller or stored: phone numbers and emails are masked, the
customer's name is never read, a thread is identified only by an anonymized
``conversation_ref`` (``chat#`` + short hash), and the page's own replies are
skipped (we only want the customer's voice).

Relevance uses a chat-tuned filter (``inbox`` section of config/keywords.yaml).
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
from pipeline.config_loader import load_keywords  # noqa: E402
from scrapers.facebook import GRAPH_BASE, _get_token, _parse_time  # noqa: E402

load_dotenv(override=True)

logger = logging.getLogger(__name__)

CONV_LIMIT          = 50    # conversations per page (FB rejects bigger pulls)
MSG_LIMIT           = 50    # messages per block
LIGHT_LOOKBACK_DAYS = 14    # daily run: only look back this far
LIGHT_MAX_PAGES     = 6     # daily run: cap conversation pages (~300 convs)
DEEP_LOOKBACK_DAYS  = 365   # backfill default window
PACE_SECONDS        = 0.1   # gentle gap between API calls
RATE_LIMIT_CODES    = {4, 17, 32, 341, 613}   # FB "slow down" / quota codes

# ── PII masking ─────────────────────────────────────────────────────────────

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# VN phone numbers: 0/+84 prefix then 8–10 digits with optional separators. We
# require the prefix (not any long digit run) so a loan amount like
# "2000000000 đồng" stays intact instead of being wrongly hidden.
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?84|0)[\s.\-]?(?:\d[\s.\-]?){7,9}\d(?!\d)")


def _mask_pii(text: str) -> str:
    return _PHONE_RE.sub("[số điện thoại]", _EMAIL_RE.sub("[email]", text))


def _anon_ref(conversation_id: str) -> str:
    h = hashlib.sha1(conversation_id.encode("utf-8")).hexdigest()[:6]
    return f"chat#{h}"


# ── Relevance (chat-tuned) ──────────────────────────────────────────────────

def _inbox_filter(kw_cfg: dict):
    cfg = kw_cfg.get("inbox", {})
    return cfg.get("include", []), cfg.get("exclude", [])


def _is_relevant(text: str, include: list, exclude: list) -> bool:
    t = (text or "").lower()
    return any(k.lower() in t for k in include) and not any(e.lower() in t for e in exclude)


def _parse_dt(raw: str) -> Optional[datetime]:
    try:
        return datetime.strptime(raw, "%Y-%m-%dT%H:%M:%S%z")
    except (ValueError, TypeError):
        return None


# ── Rate-limited API access with a call budget ──────────────────────────────

class _Budget:
    """Counts API calls so a backfill can't run away. Raises when exhausted."""
    def __init__(self, max_calls: int):
        self.max = max_calls
        self.n = 0

    def take(self) -> None:
        self.n += 1
        if self.n > self.max:
            raise RuntimeError(f"API call budget ({self.max}) exhausted")


def _api_get(url: str, params: Optional[dict], budget: _Budget) -> dict:
    """GET with pacing + exponential back-off on Facebook rate-limit codes."""
    for attempt in range(5):
        budget.take()
        time.sleep(PACE_SECONDS)
        try:
            resp = requests.get(url, params=params, timeout=25)
        except requests.exceptions.RequestException as exc:
            logger.warning("Request failed (%s), retrying…", exc)
            time.sleep(3 * (attempt + 1))
            continue
        if resp.status_code == 200:
            return resp.json()
        err = {}
        try:
            err = resp.json().get("error", {})
        except Exception:
            pass
        code = err.get("code")
        if code in RATE_LIMIT_CODES:
            wait = 30 * (attempt + 1)
            logger.warning("Rate limited (code %s) — backing off %ds", code, wait)
            time.sleep(wait)
            continue
        logger.warning("Graph error (code %s): %s", code, str(err.get("message"))[:120])
        return {}
    logger.warning("Giving up on %s after retries", url.split("?")[0])
    return {}


# ── Pagination iterators ────────────────────────────────────────────────────

def _iter_conversations(page_id, token, cutoff, budget, max_pages=None):
    """Yield conversation objects (with an inline first page of messages),
    newest first, stopping once a conversation predates the cutoff."""
    url = f"{GRAPH_BASE}/{page_id}/conversations"
    params = {
        "access_token": token,
        "fields": f"id,updated_time,message_count,"
                  f"messages.limit({MSG_LIMIT}){{id,message,created_time,from}}",
        "limit": CONV_LIMIT,
    }
    pages = 0
    while url:
        data = _api_get(url, params, budget)
        if "data" not in data:
            return
        for conv in data["data"]:
            udt = _parse_dt(conv.get("updated_time", ""))
            if udt and udt < cutoff:
                return  # ordered newest-first → everything after is older too
            yield conv
        pages += 1
        if max_pages and pages >= max_pages:
            return
        url = data.get("paging", {}).get("next")
        params = None


def _iter_older_messages(conv_id, token, cutoff, budget):
    """Page a thread's messages past the inline first block, until the cutoff."""
    url = f"{GRAPH_BASE}/{conv_id}/messages"
    params = {"access_token": token,
              "fields": "id,message,created_time,from", "limit": MSG_LIMIT}
    while url:
        data = _api_get(url, params, budget)
        msgs = data.get("data")
        if not msgs:
            return
        for m in msgs:
            mdt = _parse_dt(m.get("created_time", ""))
            if mdt and mdt < cutoff:
                return
            yield m
        url = data.get("paging", {}).get("next")
        params = None


# ── Public interface ────────────────────────────────────────────────────────

def scrape(deep: bool = False, lookback_days: Optional[int] = None,
           max_calls: int = 3000) -> list[dict]:
    """Return home-loan inbox messages as masked, anonymized dicts.

    ``deep=False`` (default): light daily run — recent conversations only.
    ``deep=True``: full block-by-block backfill over ``lookback_days`` (defaults
    to 365), paging into long threads. ``max_calls`` caps total API calls.

    Never raises on API trouble; returns whatever was collected (so a partial
    backfill still persists — re-running resumes via fb_message_id dedup).
    """
    token   = _get_token()
    page_id = os.getenv("FACEBOOK_PAGE_ID")
    if not token or not page_id:
        logger.info("Inbox: no FACEBOOK_ACCESS_TOKEN / FACEBOOK_PAGE_ID — skipping.")
        return []

    include, exclude = _inbox_filter(load_keywords())
    if not include:
        logger.warning("Inbox: no 'inbox.include' keywords in config — skipping.")
        return []

    days = lookback_days if lookback_days is not None else (
        DEEP_LOOKBACK_DAYS if deep else LIGHT_LOOKBACK_DAYS)
    cutoff   = datetime.now(timezone.utc) - timedelta(days=days)
    budget   = _Budget(max_calls)
    max_pages = None if deep else LIGHT_MAX_PAGES

    results: list[dict] = []
    seen: set = set()
    convs = deep_threads = 0

    def _consume(messages, ref):
        for m in messages:
            if str((m.get("from") or {}).get("id", "")) == str(page_id):
                continue
            mdt = _parse_dt(m.get("created_time", ""))
            if mdt and mdt < cutoff:
                continue
            text = (m.get("message") or "").strip()
            if not text or not _is_relevant(text, include, exclude):
                continue
            fb_id = m.get("id")
            if not fb_id or fb_id in seen:
                continue
            seen.add(fb_id)
            results.append({
                "fb_message_id":    fb_id,
                "conversation_ref": ref,
                "message":          _mask_pii(text),
                "sent_at":          _parse_time(m.get("created_time", "")),
            })

    try:
        for conv in _iter_conversations(page_id, token, cutoff, budget, max_pages):
            convs += 1
            ref = _anon_ref(str(conv.get("id", "")))
            inline = conv.get("messages", {}).get("data", [])
            _consume(inline, ref)
            # Deep mode: long threads have more messages than the inline block.
            if deep and int(conv.get("message_count", 0) or 0) > len(inline):
                deep_threads += 1
                _consume(_iter_older_messages(conv["id"], token, cutoff, budget), ref)
            if convs % 200 == 0:
                logger.info("  …%d conversations, %d relevant so far (%d API calls)",
                            convs, len(results), budget.n)
    except RuntimeError as exc:
        logger.warning("Inbox backfill stopped early: %s — keeping partial results.", exc)

    logger.info("Inbox %s scan: %d conversations (%d deep threads), "
                "%d relevant home-loan messages, %d API calls",
                "DEEP" if deep else "light", convs, deep_threads, len(results), budget.n)
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    deep = "--deep" in sys.argv or os.getenv("INBOX_DEEP") == "1"
    rows = scrape(deep=deep)
    print(f"\nRelevant inbox messages: {len(rows)}\n")
    for i, r in enumerate(rows[:10], 1):
        print(f"--- {i} [{r['conversation_ref']}] {r['sent_at']} ---")
        print(r["message"][:120])
        print()
