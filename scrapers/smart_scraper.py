"""Smart scraper — tries requests/BS4 first, falls back to Firecrawl for blocked/JS sites."""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
from pipeline.config_loader import load_keywords, load_settings, load_sources  # noqa: E402
from pipeline.timeutils import now_iso  # noqa: E402

load_dotenv()

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8",
}

_CHALLENGE_SIGNALS = [
    "cloudflare", "captcha", "challenge", "just a moment",
    "checking your browser", "ddos-guard", "enable javascript",
    "please wait", "bot protection",
]

# JS frameworks that server-side render very little content — Firecrawl handles these better
_JS_FRAMEWORK_SIGNALS = ["__next", "_next/", "__NUXT__", "data-reactroot", "ng-version"]


# ── Challenge detection ───────────────────────────────────────────────────────

def _is_blocked(status_code: int, text: str) -> bool:
    if status_code in (403, 429, 503):
        return True
    snippet = text[:3000].lower()
    return any(s in snippet for s in _CHALLENGE_SIGNALS)


def _needs_firecrawl(status_code: int, text: str, soup: BeautifulSoup) -> Optional[str]:
    """Return a reason string if Firecrawl is needed, else None."""
    if status_code in (403, 429, 503):
        return f"blocked (HTTP {status_code})"
    snippet = text[:3000].lower()
    if any(s in snippet for s in _CHALLENGE_SIGNALS):
        return "bot/captcha challenge"
    if len(soup.find_all("a", href=True)) < 5:
        return "JS-rendered (almost no links in static HTML)"
    if any(s in text for s in _JS_FRAMEWORK_SIGNALS):
        return "JS framework detected (Next.js/Nuxt/React)"
    return None


# ── Transport layer ───────────────────────────────────────────────────────────

def _fetch_plain(url: str, delay: float):
    """Returns (soup, reason).  reason=None means plain fetch is usable."""
    time.sleep(delay)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
    except Exception as exc:
        return None, f"request failed: {exc}"

    resp.encoding = "utf-8"
    soup = BeautifulSoup(resp.text, "lxml")
    reason = _needs_firecrawl(resp.status_code, resp.text, soup)
    if reason:
        return None, reason
    return soup, None


def _fetch_firecrawl(url: str):
    """Returns markdown string via Firecrawl, or None on failure. Logs each credit used."""
    api_key = os.getenv("FIRECRAWL_API_KEY")
    if not api_key:
        logger.warning("FIRECRAWL_API_KEY not set — cannot fallback for %s", url)
        return None
    try:
        from firecrawl import V1FirecrawlApp
        app = V1FirecrawlApp(api_key=api_key)
        result = app.scrape_url(url, formats=["markdown", "links"])
        # Log 1 credit used (~$0.005 on paid tier, free on free tier)
        try:
            from pipeline.collector import log_usage
            log_usage("firecrawl", "scrape_url", items_processed=1)
        except Exception:
            pass
        return result.markdown or ""
    except Exception as exc:
        logger.warning("Firecrawl failed for %s: %s", url, exc)
        return None


# ── Firecrawl generic article extractor ──────────────────────────────────────

def _extract_from_markdown(md: str, source_url: str,
                            label: str, keywords: list, negatives: list) -> list:
    from scrapers.firecrawl_scraper import _extract_articles, _is_relevant
    pairs = _extract_articles(md, source_url)
    results = []
    for title, article_url in pairs:
        if _is_relevant(title, keywords, negatives):
            results.append({
                "source":     label,
                "source_url": source_url,
                "title":      title,
                "summary":    "",
                "url":        article_url,
                "scraped_at": now_iso(),
            })
    return results


# ── Config helpers ────────────────────────────────────────────────────────────

# ── Public entry point ────────────────────────────────────────────────────────

def scrape() -> list:
    from scrapers.news import (
        _PARSERS as NEWS_PARSERS,
        _all_keywords as news_kw,
        _negative_keywords as news_neg,
    )
    from scrapers.forums import _PARSERS as FORUM_PARSERS
    from scrapers.firecrawl_scraper import _SOURCE_LABELS, _all_keywords as fc_kw

    kw_cfg       = load_keywords()
    src_cfg      = load_sources()
    settings_cfg = load_settings()
    delay = settings_cfg.get("scraping", {}).get("delay_between_requests", 2)

    news_keywords = news_kw(kw_cfg)
    news_negatives = news_neg(kw_cfg)

    all_results = []

    # ── News sites ────────────────────────────────────────────────────────────
    for site in src_cfg.get("news_sites", []):
        name = site["name"]
        url  = site["url"]
        label = _SOURCE_LABELS.get(name, name)
        parser_fn = NEWS_PARSERS.get(name)

        if not parser_fn:
            logger.warning("No parser for news site: %s", name)
            continue

        logger.info("Scraping %s...", name)
        soup, reason = _fetch_plain(url, delay)

        if soup is not None:
            items = parser_fn(soup, url, news_keywords, news_negatives)
            logger.info("  → %d via requests (%s)", len(items), name)
            if items:
                all_results.extend(items)
            else:
                logger.info("  → 0 from requests, trying Firecrawl (%s)", name)
                md = _fetch_firecrawl(url)
                if md:
                    items = _extract_from_markdown(md, url, label, news_keywords, news_negatives)
                    logger.info("  → %d via Firecrawl (%s)", len(items), name)
                    all_results.extend(items)
        else:
            logger.info("  → Firecrawl fallback [%s] for %s", reason, name)
            md = _fetch_firecrawl(url)
            if md:
                items = _extract_from_markdown(md, url, label, news_keywords, news_negatives)
                logger.info("  → %d via Firecrawl (%s)", len(items), name)
                all_results.extend(items)

    # ── Forums ────────────────────────────────────────────────────────────────
    forum_keywords = fc_kw(kw_cfg, include_forum=True)
    forum_negatives = news_neg(kw_cfg)

    for forum in src_cfg.get("forums", []):
        name  = forum["name"]
        url   = forum.get("url", "")
        if not url:
            continue

        parser_entry = FORUM_PARSERS.get(name)
        if not parser_entry:
            logger.warning("No parser for forum: %s", name)
            continue

        parser_fn, label = parser_entry
        logger.info("Scraping forum %s...", name)
        soup, reason = _fetch_plain(url, delay)

        if soup is not None:
            items = parser_fn(soup, url, label, forum_keywords, forum_negatives)
            logger.info("  → %d via requests (%s)", len(items), name)
            if items:
                all_results.extend(items)
            else:
                logger.info("  → 0 from requests, trying Firecrawl (%s)", name)
                md = _fetch_firecrawl(url)
                if md:
                    items = _extract_from_markdown(md, url, label, forum_keywords, forum_negatives)
                    logger.info("  → %d via Firecrawl (%s)", len(items), name)
                    all_results.extend(items)
        else:
            logger.info("  → Firecrawl fallback [%s] for %s", reason, name)
            md = _fetch_firecrawl(url)
            if md:
                items = _extract_from_markdown(md, url, label, forum_keywords, forum_negatives)
                logger.info("  → %d via Firecrawl (%s)", len(items), name)
                all_results.extend(items)

    return all_results


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    results = scrape()
    print(f"\nTotal relevant articles: {len(results)}\n")
    fc_count  = sum(1 for r in results if not r.get("summary"))  # Firecrawl results have no summary
    bs4_count = len(results) - fc_count
    for i, r in enumerate(results[:5], 1):
        print(f"--- {i} [{r['source']}] ---")
        print(f"Title : {r['title']}")
        print(f"URL   : {r['url']}")
        print()
