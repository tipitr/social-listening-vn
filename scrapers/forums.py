"""Forum scraper: OTOFUN, 6Giay — Vietnamese home loan discussion threads."""

import logging
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent.parent))
from pipeline.config_loader import load_keywords, load_settings, load_sources  # noqa: E402
from pipeline.timeutils import now_iso  # noqa: E402

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8",
}


def _all_keywords(keywords_cfg):
    kw = keywords_cfg.get("home_loan", {})
    # Forums use short thread titles — include forum_keywords for broader matching
    return (
        kw.get("vietnamese", [])
        + kw.get("interest_rate", [])
        + kw.get("credit", [])
        + kw.get("promotions", [])
        + kw.get("forum_keywords", [])
    )


def _negative_keywords(keywords_cfg):
    return keywords_cfg.get("home_loan", {}).get("negative_filter", [])


def _is_relevant(text, keywords, negatives):
    text_lower = text.lower()
    has_kw  = any(k.lower() in text_lower for k in keywords)
    is_noise = any(n.lower() in text_lower for n in negatives)
    return has_kw and not is_noise


def _get_soup(url, delay):
    time.sleep(delay)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = "utf-8"
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")
    except Exception as exc:
        logger.warning("Failed to fetch %s: %s", url, exc)
        return None


# ---------------------------------------------------------------------------
# OTOFUN — XenForo-based forum (otofun.net)
# Thread list: .structItem--thread  |  title: .structItem-title a[data-tp-primary]
# ---------------------------------------------------------------------------

def _parse_otofun(soup, source_url, source_name, keywords, negatives):
    results = []
    for item in soup.select(".structItem--thread"):
        title_tag = (
            item.select_one(".structItem-title a[data-tp-primary]")
            or item.select_one(".structItem-title a")
        )
        if not title_tag:
            continue
        title = title_tag.get_text(strip=True)
        href  = title_tag.get("href", "")
        if not href.startswith("http"):
            href = "https://www.otofun.net" + href

        # Thread preview snippet if available
        preview_tag = item.select_one(".structItem-minor, .structItem-body p")
        summary = preview_tag.get_text(strip=True) if preview_tag else ""

        if not _is_relevant(f"{title} {summary}", keywords, negatives):
            continue

        results.append({
            "source":     source_name,
            "source_url": source_url,
            "title":      title,
            "summary":    summary,
            "url":        href,
            "scraped_at": now_iso(),
        })
    return results


# ---------------------------------------------------------------------------
# 6Giay — news/forum hybrid (6giay.vn)
# Article list: .post-title a  |  summary: sibling p
# ---------------------------------------------------------------------------

def _parse_6giay(soup, source_url, source_name, keywords, negatives):
    results = []
    for item in soup.select(".post-title a, h2 a[href]"):
        title = item.get_text(strip=True)
        href  = item.get("href", "")
        if not href.startswith("http"):
            href = "https://6giay.vn" + href

        summary = ""
        parent = item.find_parent(["li", "div", "article"])
        if parent:
            p_tag = parent.find("p")
            if p_tag:
                summary = p_tag.get_text(strip=True)

        if not _is_relevant(f"{title} {summary}", keywords, negatives):
            continue

        results.append({
            "source":     source_name,
            "source_url": source_url,
            "title":      title,
            "summary":    summary,
            "url":        href,
            "scraped_at": now_iso(),
        })
    return results


# ---------------------------------------------------------------------------
# Parser registry
# ---------------------------------------------------------------------------

_PARSERS = {
    "OTOFUN_RealEstate":  (_parse_otofun, "OTOFUN"),
    "OTOFUN_Construction":(_parse_otofun, "OTOFUN"),
    "OTOFUN_Cafe":        (_parse_otofun, "OTOFUN"),
    "6Giay":              (_parse_6giay,  "6Giay"),
}


def scrape() -> list[dict]:
    keywords_cfg = load_keywords()
    sources_cfg  = load_sources()
    settings_cfg = load_settings()
    keywords  = _all_keywords(keywords_cfg)
    negatives = _negative_keywords(keywords_cfg)
    delay     = settings_cfg.get("scraping", {}).get("delay_between_requests", 2)

    all_results = []
    for forum in sources_cfg.get("forums", []):
        name = forum["name"]
        url  = forum.get("url") or forum.get("search_url", "")

        parser_entry = _PARSERS.get(name)
        if not parser_entry:
            logger.warning("No parser for forum: %s", name)
            continue

        parser_fn, source_label = parser_entry
        logger.info("Scraping forum %s (%s)", name, url)
        soup = _get_soup(url, delay)
        if soup is None:
            continue

        try:
            items = parser_fn(soup, url, source_label, keywords, negatives)
            logger.info("  → %d relevant threads from %s", len(items), name)
            all_results.extend(items)
        except Exception as exc:
            logger.error("Error parsing forum %s: %s", name, exc)

    return all_results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    results = scrape()
    print(f"\nTotal relevant forum threads: {len(results)}\n")
    for i, r in enumerate(results[:5], 1):
        print(f"--- Thread {i} ---")
        print(f"Source  : {r['source']}")
        print(f"Title   : {r['title']}")
        print(f"Summary : {r['summary'][:120]}" if r['summary'] else "Summary : (none)")
        print(f"URL     : {r['url']}")
        print()
