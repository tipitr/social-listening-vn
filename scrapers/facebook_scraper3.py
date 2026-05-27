"""Facebook scraper using the RapidAPI "Facebook Scraper3" service.

Why this exists alongside scrapers/facebook.py:
    scrapers/facebook.py needs an official Meta Graph API token (App ID +
    Secret). Getting one takes 30 minutes for basic access and up to 2 weeks
    for advanced permissions. This module is the bridge: it uses a RapidAPI
    marketplace service so the team can start collecting Facebook signal in
    5 minutes (just an API key, no Meta app review).

How it activates:
    set ``RAPIDAPI_KEY`` in ``.env`` → ``pipeline.collector.collect_all()``
    picks this scraper up automatically. If the key is missing, ``scrape()``
    returns ``[]`` cleanly and the pipeline carries on with news + forums.

Two HTTP calls per Facebook page:
    1. ``GET /search/pages?query=<name>`` — find the numeric Facebook ID
       (RapidAPI service rejects usernames; needs the numeric id).
    2. ``GET /page/posts?page_id=<id>`` — return up to 20 recent posts.

We then run the same relevance filter as scrapers/facebook.py: a post only
makes it into the database if it mentions one of the home-loan keywords from
config/keywords.yaml AND none of the negative filter words.

Cost: free tier is 30 calls/day → enough for ~15 pages/day. Paid tier
($9.99/mo) gets 10k/day.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
from pipeline.config_loader import load_keywords, load_sources  # noqa: E402
from pipeline.timeutils import LOCAL_TZ, now_iso  # noqa: E402

load_dotenv()

logger = logging.getLogger(__name__)

# ─── RapidAPI config ────────────────────────────────────────────────────────

RAPIDAPI_HOST = "facebook-scraper3.p.rapidapi.com"
RAPIDAPI_BASE = f"https://{RAPIDAPI_HOST}"
POST_LIMIT    = 20      # max posts to fetch per page per run
TIMEOUT_SEC   = 20      # ceiling per RapidAPI call; service usually answers in <5s


def _api_key() -> Optional[str]:
    """Lazy read so tests can monkeypatch the env var after import."""
    key = os.getenv("RAPIDAPI_KEY", "").strip()
    return key or None


def _headers() -> dict:
    return {
        "x-rapidapi-key":  _api_key() or "",
        "x-rapidapi-host": RAPIDAPI_HOST,
    }


# ─── Keyword filtering (mirrors scrapers/facebook.py) ───────────────────────

def _all_keywords(kw_cfg: dict) -> list:
    kw = kw_cfg.get("home_loan", {})
    # Include forum_keywords — FB posts are short, like forum threads
    return (
        kw.get("vietnamese", [])
        + kw.get("interest_rate", [])
        + kw.get("credit", [])
        + kw.get("promotions", [])
        + kw.get("forum_keywords", [])
    )


def _negative_keywords(kw_cfg: dict) -> list:
    return kw_cfg.get("home_loan", {}).get("negative_filter", [])


def _is_relevant(text: str, keywords: list, negatives: list) -> bool:
    t = (text or "").lower()
    return any(k.lower() in t for k in keywords) and not any(n.lower() in t for n in negatives)


# ─── RapidAPI calls ─────────────────────────────────────────────────────────

def _get_page_id(page_name: str) -> Optional[str]:
    """Resolve a page username/name to its numeric Facebook ID.

    The /page/posts endpoint won't accept a username — it needs the numeric
    id. We pay one extra call per page per scrape to discover it.

    Returns None on any failure so the caller can skip the page cleanly.
    """
    try:
        resp = requests.get(
            f"{RAPIDAPI_BASE}/search/pages",
            headers=_headers(),
            params={"query": page_name},
            timeout=TIMEOUT_SEC,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.RequestException as exc:
        logger.warning("RapidAPI /search/pages failed for %s: %s", page_name, exc)
        return None
    except Exception as exc:
        logger.warning("Unexpected error resolving %s: %s", page_name, exc)
        return None

    # Schema in the wild: {"results": [{facebook_id, id, page_id, name, ...}]}
    candidates = data.get("results") or data.get("data") or []
    if not candidates:
        logger.info("Facebook page not found via RapidAPI: %s", page_name)
        return None

    first = candidates[0]
    # Different endpoints return the id under different keys — try each.
    return (
        first.get("facebook_id")
        or first.get("page_id")
        or first.get("id")
    )


def _get_page_posts(page_id: str, page_name: str) -> list[dict]:
    """Fetch recent posts from a page by its numeric id.

    Returns a list of post dicts straight from the API — caller is responsible
    for filtering and normalising.
    """
    try:
        resp = requests.get(
            f"{RAPIDAPI_BASE}/page/posts",
            headers=_headers(),
            params={"page_id": page_id},
            timeout=TIMEOUT_SEC,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.RequestException as exc:
        logger.warning("RapidAPI /page/posts failed for %s (id=%s): %s",
                       page_name, page_id, exc)
        return []
    except Exception as exc:
        logger.warning("Unexpected error fetching posts for %s: %s", page_name, exc)
        return []

    # Different shapes seen in working repos — accept any of these.
    return (
        data.get("results")
        or data.get("data")
        or data.get("posts")
        or []
    )


# ─── Normalisation ──────────────────────────────────────────────────────────

def _parse_timestamp(post: dict) -> str:
    """Convert various timestamp shapes the API returns into our ISO format.

    Accepts:
      - "timestamp": 1716800000          (unix seconds)
      - "created_time": "2024-...Z"      (ISO)
      - "time": "2 days ago"             (relative — falls back to now)
    """
    ts = post.get("timestamp")
    if ts:
        try:
            dt = datetime.fromtimestamp(int(ts), tz=LOCAL_TZ).replace(tzinfo=None)
            return dt.isoformat()
        except (TypeError, ValueError):
            pass

    created = post.get("created_time") or post.get("publish_time")
    if created:
        try:
            return datetime.fromisoformat(str(created).replace("Z", "")).isoformat()
        except ValueError:
            pass

    # "2 days ago" style or missing — fall back to scrape time.
    return now_iso()


def _post_to_article(post: dict, page_name: str,
                     keywords: list, negatives: list) -> Optional[dict]:
    """Turn a raw API post into the shape pipeline.collector.save() expects."""
    text = (post.get("message") or post.get("text") or post.get("story") or "").strip()
    if not text:
        return None
    if not _is_relevant(text, keywords, negatives):
        return None

    url = post.get("url") or post.get("post_url") or ""
    if not url:
        post_id = post.get("post_id") or post.get("id")
        if post_id:
            url = f"https://facebook.com/{post_id}"

    return {
        "source":     page_name,
        "source_url": f"https://facebook.com/{page_name}",
        "title":      text[:200].replace("\n", " "),
        "summary":    text,
        "url":        url,
        "scraped_at": _parse_timestamp(post),
    }


# ─── Public entry point ─────────────────────────────────────────────────────

def scrape() -> list[dict]:
    """Walk every page in config/sources.yaml's ``facebook_pages`` list and
    return the relevant home-loan posts as article dicts.

    If RAPIDAPI_KEY isn't set, returns [] without raising — so the daily
    pipeline degrades gracefully when the key is missing.
    """
    if not _api_key():
        logger.info("RAPIDAPI_KEY not set — skipping Facebook (RapidAPI) scraper.")
        return []

    kw_cfg  = load_keywords()
    src_cfg = load_sources()
    keywords  = _all_keywords(kw_cfg)
    negatives = _negative_keywords(kw_cfg)

    all_results: list[dict] = []

    for page in src_cfg.get("facebook_pages", []):
        page_name = page["name"]
        # The "page_id" in sources.yaml is the FB username (e.g. "Vietcombank").
        # We use it as the search query — RapidAPI returns the numeric id.
        search_name = page.get("page_id", page_name)

        logger.info("Facebook (RapidAPI): %s", page_name)
        numeric_id = _get_page_id(search_name)
        if not numeric_id:
            continue

        posts = _get_page_posts(numeric_id, page_name)
        logger.info("  → %d posts fetched", len(posts))

        hits = 0
        for post in posts:
            article = _post_to_article(post, page_name, keywords, negatives)
            if article:
                all_results.append(article)
                hits += 1

        logger.info("  → %d relevant posts from %s", hits, page_name)

    return all_results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    results = scrape()
    print(f"\nTotal relevant FB posts (RapidAPI): {len(results)}\n")
    for i, r in enumerate(results[:5], 1):
        print(f"--- {i} [{r['source']}] ---")
        print(f"Title : {r['title'][:80]}")
        print(f"URL   : {r['url']}")
        print()
