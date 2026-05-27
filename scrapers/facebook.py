"""Facebook Graph API scraper — reads public posts and comments from bank pages."""

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

load_dotenv(override=True)  # see pipeline/categorizer.py for rationale

logger = logging.getLogger(__name__)

GRAPH_BASE  = "https://graph.facebook.com/v19.0"
POST_FIELDS = "id,message,story,created_time,permalink_url"
POST_LIMIT  = 20
COMMENT_LIMIT = 10


# ── Config ────────────────────────────────────────────────────────────────────

def _all_keywords(kw_cfg) -> list:
    """Strict home-loan-only keywords for FB pages.

    forum_keywords is intentionally NOT included. Those short terms
    (``"lãi suất"``, ``"vay nhà"``) work for forum thread titles, but
    bank FB pages publish car-loan / business-loan / credit-card promos
    that also mention ``"lãi suất"`` and would slip through. The four
    lists kept here every term contains an explicit housing word
    (``"mua nhà"``, ``"căn hộ"``, ``"chung cư"``, ``"bất động sản"``,
    ``"thế chấp"``) so only home-loan posts match.
    """
    kw = kw_cfg.get("home_loan", {})
    return (
        kw.get("vietnamese", [])
        + kw.get("interest_rate", [])
        + kw.get("credit", [])
        + kw.get("promotions", [])
    )


def _negative_keywords(kw_cfg) -> list:
    return kw_cfg.get("home_loan", {}).get("negative_filter", [])


def _is_relevant(text: str, keywords: list, negatives: list) -> bool:
    t = (text or "").lower()
    return any(k.lower() in t for k in keywords) and not any(n.lower() in t for n in negatives)


def _get_token() -> Optional[str]:
    """User access token if available, otherwise App token (App ID|Secret)."""
    user_token = os.getenv("FACEBOOK_ACCESS_TOKEN")
    if user_token:
        return user_token
    app_id     = os.getenv("FACEBOOK_APP_ID")
    app_secret = os.getenv("FACEBOOK_APP_SECRET")
    if app_id and app_secret:
        return f"{app_id}|{app_secret}"
    return None


# ── Graph API calls ───────────────────────────────────────────────────────────

def _graph_get(path: str, token: str, **params) -> dict:
    resp = requests.get(
        f"{GRAPH_BASE}/{path}",
        params={"access_token": token, **params},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def _fetch_posts(page_id: str, token: str) -> list[dict]:
    try:
        data = _graph_get(f"{page_id}/posts", token, fields=POST_FIELDS, limit=POST_LIMIT)
        return data.get("data", [])
    except requests.exceptions.HTTPError as exc:
        err = {}
        try:
            err = exc.response.json().get("error", {})
        except Exception:
            pass
        logger.warning("Graph API error for %s: %s (code %s)", page_id, err.get("message"), err.get("code"))
        return []
    except Exception as exc:
        logger.warning("Failed to fetch posts for %s: %s", page_id, exc)
        return []


def _fetch_comments(post_id: str, token: str) -> list[dict]:
    try:
        data = _graph_get(
            f"{post_id}/comments", token,
            fields="id,message,created_time",
            limit=COMMENT_LIMIT,
        )
        return data.get("data", [])
    except Exception as exc:
        logger.debug("Failed to fetch comments for %s: %s", post_id, exc)
        return []


# ── Conversion helpers ────────────────────────────────────────────────────────

def _parse_time(raw: str) -> str:
    """Convert Graph API timestamp (TZ-aware) to GMT+7 naive ISO string."""
    try:
        utc_dt = datetime.strptime(raw, "%Y-%m-%dT%H:%M:%S%z")
        return utc_dt.astimezone(LOCAL_TZ).replace(tzinfo=None).isoformat()
    except ValueError:
        return now_iso()


def _post_to_article(post: dict, page_name: str, page_url: str,
                     keywords: list, negatives: list) -> Optional[dict]:
    text = (post.get("message") or post.get("story") or "").strip()
    if not text:
        return None
    if not _is_relevant(text, keywords, negatives):
        return None
    return {
        "source":     page_name,
        "source_url": page_url,
        "title":      text[:200].replace("\n", " "),
        "summary":    text,
        "url":        post.get("permalink_url") or f"https://facebook.com/{post['id']}",
        "scraped_at": _parse_time(post.get("created_time", "")),
    }


def _comment_to_article(comment: dict, page_name: str, post_url: str,
                         keywords: list, negatives: list) -> Optional[dict]:
    text = (comment.get("message") or "").strip()
    if not text or not _is_relevant(text, keywords, negatives):
        return None
    return {
        "source":     f"{page_name}",
        "source_url": post_url,
        "title":      text[:200].replace("\n", " "),
        "summary":    text,
        "url":        post_url,
        "scraped_at": _parse_time(comment.get("created_time", "")),
    }


# ── Public interface ──────────────────────────────────────────────────────────

def scrape(include_comments: bool = True) -> list[dict]:
    token = _get_token()
    if not token:
        logger.error(
            "No Facebook credentials. Set FACEBOOK_ACCESS_TOKEN "
            "or FACEBOOK_APP_ID + FACEBOOK_APP_SECRET in .env"
        )
        return []

    kw_cfg  = load_keywords()
    src_cfg = load_sources()
    keywords  = _all_keywords(kw_cfg)
    negatives = _negative_keywords(kw_cfg)

    all_results = []

    for page in src_cfg.get("facebook_pages", []):
        page_name = page["name"]
        page_id   = page["page_id"]
        page_url  = f"https://facebook.com/{page_id}"

        logger.info("Facebook: %s (%s)", page_name, page_id)
        posts = _fetch_posts(page_id, token)
        logger.info("  → %d posts fetched", len(posts))

        post_hits    = 0
        comment_hits = 0

        for post in posts:
            article = _post_to_article(post, page_name, page_url, keywords, negatives)
            if article:
                all_results.append(article)
                post_hits += 1

            if include_comments:
                post_url = post.get("permalink_url") or f"https://facebook.com/{post['id']}"
                for comment in _fetch_comments(post["id"], token):
                    c = _comment_to_article(comment, page_name, post_url, keywords, negatives)
                    if c:
                        all_results.append(c)
                        comment_hits += 1

        logger.info("  → %d posts + %d comments relevant from %s",
                    post_hits, comment_hits, page_name)

    return all_results


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    results = scrape()
    print(f"\nTotal relevant Facebook items: {len(results)}\n")
    for i, r in enumerate(results[:5], 1):
        print(f"--- {i} [{r['source']}] ---")
        print(f"Title : {r['title'][:80]}")
        print(f"URL   : {r['url']}")
        print()
