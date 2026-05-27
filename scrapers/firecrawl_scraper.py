"""Firecrawl-based scraper — one generic parser for all sources including JS-rendered sites."""

import logging
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
from pipeline.config_loader import load_keywords, load_sources  # noqa: E402
from pipeline.timeutils import now_iso  # noqa: E402

load_dotenv(override=True)  # see pipeline/categorizer.py for rationale

logger = logging.getLogger(__name__)

_MD_LINK = re.compile(r'\[([^\]]{8,250})\]\((https?://[^\s\)\]"]+)')

_SOURCE_LABELS = {
    "CafeF": "CafeF", "CafeF_Banking": "CafeF",
    "VnExpress": "VnExpress", "VnExpress_Banking": "VnExpress",
    "CafeLand": "CafeLand", "VnEconomy": "VnEconomy",
    "VietnamNet": "VietnamNet", "BatDongSan": "BatDongSan",
    "DanTri": "DanTri", "TuoiTre": "TuoiTre",
    "OTOFUN_RealEstate": "OTOFUN", "OTOFUN_Construction": "OTOFUN",
    "OTOFUN_Cafe": "OTOFUN", "6Giay": "6Giay",
}

_SKIP_PATTERNS = ["?page=", "/tag/", "/tags/", "/author/", "/search", "#", "javascript:"]


def _all_keywords(keywords_cfg, include_forum=False):
    kw = keywords_cfg.get("home_loan", {})
    keys = (
        kw.get("vietnamese", [])
        + kw.get("interest_rate", [])
        + kw.get("credit", [])
        + kw.get("promotions", [])
    )
    if include_forum:
        keys += kw.get("forum_keywords", [])
    return keys


def _negative_keywords(keywords_cfg):
    return keywords_cfg.get("home_loan", {}).get("negative_filter", [])


def _is_relevant(text, keywords, negatives):
    t = text.lower()
    return any(k.lower() in t for k in keywords) and not any(n.lower() in t for n in negatives)


def _base_domain(url):
    return urlparse(url).netloc.lower().lstrip("www.")


def _extract_articles(markdown, source_url):
    """Parse markdown [title](url) links, keeping only same-domain article links."""
    domain = _base_domain(source_url)
    seen = set()
    pairs = []
    for title, url in _MD_LINK.findall(markdown):
        title = title.strip()
        # Skip image alt-text captured from [![alt](img)](url) patterns
        if title.startswith("!"):
            continue
        if len(title) < 8:
            continue
        art_domain = _base_domain(url)
        if art_domain != domain and not art_domain.endswith("." + domain):
            continue
        if any(p in url.lower() for p in _SKIP_PATTERNS):
            continue
        if url not in seen:
            seen.add(url)
            pairs.append((title, url))
    return pairs


def scrape() -> list:
    api_key = os.getenv("FIRECRAWL_API_KEY")
    if not api_key:
        raise RuntimeError("FIRECRAWL_API_KEY not set in .env")

    from firecrawl import V1FirecrawlApp
    app = V1FirecrawlApp(api_key=api_key)

    keywords_cfg = load_keywords()
    sources_cfg  = load_sources()
    negatives = _negative_keywords(keywords_cfg)
    all_results = []

    for section, is_forum in [("news_sites", False), ("forums", True)]:
        keywords = _all_keywords(keywords_cfg, include_forum=is_forum)
        for site in sources_cfg.get(section, []):
            name = site["name"]
            url = site.get("url", "")
            if not url:
                continue

            label = _SOURCE_LABELS.get(name, name)
            logger.info("Firecrawl: %s", name)

            try:
                # 30s ceiling per page — Firecrawl normally responds in <10s.
                # Note: Firecrawl's timeout argument is in MILLISECONDS,
                # not seconds (minimum allowed: 1000ms).
                result = app.scrape_url(url, formats=["markdown", "links"], timeout=30000)
                md = result.markdown or ""
            except Exception as exc:
                logger.warning("Failed to scrape %s: %s", name, exc)
                continue

            pairs = _extract_articles(md, url)
            new_count = 0
            for title, article_url in pairs:
                if not _is_relevant(title, keywords, negatives):
                    continue
                all_results.append({
                    "source":     label,
                    "source_url": url,
                    "title":      title,
                    "summary":    "",
                    "url":        article_url,
                    "scraped_at": now_iso(),
                })
                new_count += 1

            logger.info("  → %d relevant from %s", new_count, name)

    return all_results


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    results = scrape()
    print(f"\nTotal relevant articles: {len(results)}\n")
    for i, r in enumerate(results[:5], 1):
        print(f"--- {i} ---")
        print(f"Source : {r['source']}")
        print(f"Title  : {r['title']}")
        print(f"URL    : {r['url']}")
        print()
