"""News scraper: CafeF, VnExpress, CafeLand, VnEconomy, VietnamNet."""

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
    # Intentionally excludes 'banks' — bank names alone match generic articles
    return (
        kw.get("vietnamese", [])
        + kw.get("interest_rate", [])
        + kw.get("credit", [])
        + kw.get("promotions", [])
    )


def _negative_keywords(keywords_cfg):
    return keywords_cfg.get("home_loan", {}).get("negative_filter", [])


def _is_relevant(text, keywords, negatives):
    text_lower = text.lower()
    has_keyword = any(k.lower() in text_lower for k in keywords)
    is_noise = any(n.lower() in text_lower for n in negatives)
    return has_keyword and not is_noise


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
# CafeF scraper
# ---------------------------------------------------------------------------

def _parse_cafef(soup, source_url, keywords, negatives):
    results = []
    # CafeF article list: <h3 class="..."><a href="...">title</a></h3>
    # and summary spans below each item
    for item in soup.select("h3 > a[href]"):
        title = item.get_text(strip=True)
        href = item["href"]
        if not href.startswith("http"):
            href = "https://cafef.vn" + href
        summary = ""
        parent_li = item.find_parent(["li", "div", "article"])
        if parent_li:
            p_tag = parent_li.find(["p", "span"], class_=lambda c: c and "sapo" in c)
            if p_tag:
                summary = p_tag.get_text(strip=True)
        combined = f"{title} {summary}"
        if not _is_relevant(combined, keywords, negatives):
            continue
        results.append({
            "source": "CafeF",
            "source_url": source_url,
            "title": title,
            "summary": summary,
            "url": href,
            "scraped_at": now_iso(),
        })
    return results


# ---------------------------------------------------------------------------
# VnExpress scraper
# ---------------------------------------------------------------------------

def _parse_vnexpress(soup, source_url, keywords, negatives):
    results = []
    # VnExpress article list: <article class="item-news"> contains <h3><a>
    for article in soup.select("article.item-news, div.item-news"):
        a_tag = article.find("h3")
        if not a_tag:
            continue
        link = a_tag.find("a", href=True)
        if not link:
            continue
        title = link.get_text(strip=True)
        href = link["href"]
        if not href.startswith("http"):
            href = "https://vnexpress.net" + href
        desc_tag = article.find("p", class_=lambda c: c and "description" in c)
        summary = desc_tag.get_text(strip=True) if desc_tag else ""
        combined = f"{title} {summary}"
        if not _is_relevant(combined, keywords, negatives):
            continue
        results.append({
            "source": "VnExpress",
            "source_url": source_url,
            "title": title,
            "summary": summary,
            "url": href,
            "scraped_at": now_iso(),
        })
    return results


# ---------------------------------------------------------------------------
# CafeLand scraper  (cafeland.vn)
# ---------------------------------------------------------------------------

def _parse_cafeland(soup, source_url, keywords, negatives):
    results = []
    for item in soup.select("h3 > a[href]"):
        title = item.get_text(strip=True)
        href = item["href"]
        if not href.startswith("http"):
            href = "https://cafeland.vn" + href
        summary = ""
        parent = item.find_parent(["li", "div", "article"])
        if parent:
            p_tag = parent.find("p")
            if p_tag:
                summary = p_tag.get_text(strip=True)
        combined = f"{title} {summary}"
        if not _is_relevant(combined, keywords, negatives):
            continue
        results.append({
            "source": "CafeLand",
            "source_url": source_url,
            "title": title,
            "summary": summary,
            "url": href,
            "scraped_at": now_iso(),
        })
    return results


# ---------------------------------------------------------------------------
# VnEconomy scraper  (vneconomy.vn)
# ---------------------------------------------------------------------------

def _parse_vneconomy(soup, source_url, keywords, negatives):
    results = []
    for item in soup.select(".story"):
        link = item.select_one(".story__title a, h3 a, h2 a")
        if not link:
            continue
        title = link.get_text(strip=True)
        href = link["href"]
        if not href.startswith("http"):
            href = "https://vneconomy.vn" + href
        desc_tag = item.select_one(".story__description, .story__summary, p")
        summary = desc_tag.get_text(strip=True) if desc_tag else ""
        combined = f"{title} {summary}"
        if not _is_relevant(combined, keywords, negatives):
            continue
        results.append({
            "source": "VnEconomy",
            "source_url": source_url,
            "title": title,
            "summary": summary,
            "url": href,
            "scraped_at": now_iso(),
        })
    return results


# ---------------------------------------------------------------------------
# VietnamNet scraper  (vietnamnet.vn)
# ---------------------------------------------------------------------------

def _parse_vietnamnet(soup, source_url, keywords, negatives):
    results = []
    for item in soup.select("h3 > a[href]"):
        title = item.get_text(strip=True)
        href = item["href"]
        if not href.startswith("http"):
            href = "https://vietnamnet.vn" + href
        summary = ""
        parent = item.find_parent(["li", "div", "article"])
        if parent:
            p_tag = parent.find("p")
            if p_tag:
                summary = p_tag.get_text(strip=True)
        combined = f"{title} {summary}"
        if not _is_relevant(combined, keywords, negatives):
            continue
        results.append({
            "source": "VietnamNet",
            "source_url": source_url,
            "title": title,
            "summary": summary,
            "url": href,
            "scraped_at": now_iso(),
        })
    return results


# ---------------------------------------------------------------------------
# DanTri scraper  (dantri.com.vn)
# ---------------------------------------------------------------------------

def _parse_dantri(soup, source_url, keywords, negatives):
    results = []
    for item in soup.select("h3 > a[href], h2 > a[href]"):
        title = item.get_text(strip=True)
        href = item["href"]
        if not href.startswith("http"):
            href = "https://dantri.com.vn" + href
        summary = ""
        parent = item.find_parent(["li", "div", "article"])
        if parent:
            p_tag = parent.find("p")
            if p_tag:
                summary = p_tag.get_text(strip=True)
        combined = f"{title} {summary}"
        if not _is_relevant(combined, keywords, negatives):
            continue
        results.append({
            "source": "DanTri",
            "source_url": source_url,
            "title": title,
            "summary": summary,
            "url": href,
            "scraped_at": now_iso(),
        })
    return results


# ---------------------------------------------------------------------------
# TuoiTre scraper  (tuoitre.vn)
# ---------------------------------------------------------------------------

def _parse_tuoitre(soup, source_url, keywords, negatives):
    results = []
    for item in soup.select("h3 > a[href], h2 > a[href]"):
        title = item.get_text(strip=True)
        href = item["href"]
        if not href.startswith("http"):
            href = "https://tuoitre.vn" + href
        summary = ""
        parent = item.find_parent(["li", "div", "article"])
        if parent:
            p_tag = parent.find("p")
            if p_tag:
                summary = p_tag.get_text(strip=True)
        combined = f"{title} {summary}"
        if not _is_relevant(combined, keywords, negatives):
            continue
        results.append({
            "source": "TuoiTre",
            "source_url": source_url,
            "title": title,
            "summary": summary,
            "url": href,
            "scraped_at": now_iso(),
        })
    return results


# ---------------------------------------------------------------------------
# BatDongSan scraper  (batdongsan.com.vn)
# Note: site is Next.js — article feed is JS-rendered.
# Only the 4 featured articles in the static HTML are accessible.
# ---------------------------------------------------------------------------

def _parse_batdongsan(soup, source_url, keywords, negatives):
    import re as _re
    DATE_PREFIX = _re.compile(
        r"^\d{2}/\d{2}/\d{4}\s*\d{2}:\d{2}\s*[•·]\s*[\w\s]+[•·]\s*"
    )
    results = []
    seen_hrefs = set()

    # h3 links give the cleanest titles (featured section)
    candidates = soup.select("h3 > a[href]")
    # Fallback: all /tin-tuc/<slug> links with meaningful text
    for a in soup.select("a[href]"):
        href = a.get("href", "")
        if _re.match(r"/tin-tuc/[a-z0-9\-]+", href) and href not in seen_hrefs:
            candidates.append(a)

    for item in candidates:
        href = item.get("href", "")
        if not href or href in seen_hrefs:
            continue
        if not href.startswith("http"):
            href = "https://batdongsan.com.vn" + href
        seen_hrefs.add(item.get("href", ""))

        raw_title = item.get_text(strip=True)
        # Strip "DD/MM/YYYY HH:MM•Category•" prefix
        title = DATE_PREFIX.sub("", raw_title).strip()
        if len(title) < 10:
            continue

        summary = ""
        parent = item.find_parent(["div", "li", "article"])
        if parent:
            p_tag = parent.find("p")
            if p_tag:
                summary = p_tag.get_text(strip=True)

        combined = f"{title} {summary}"
        if not _is_relevant(combined, keywords, negatives):
            continue

        results.append({
            "source":     "BatDongSan",
            "source_url": source_url,
            "title":      title,
            "summary":    summary,
            "url":        href,
            "scraped_at": now_iso(),
        })
    return results


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

_PARSERS = {
    "CafeF":             _parse_cafef,
    "CafeF_Banking":     _parse_cafef,
    "VnExpress":         _parse_vnexpress,
    "VnExpress_Banking": _parse_vnexpress,
    "CafeLand":          _parse_cafeland,
    "VnEconomy":         _parse_vneconomy,
    "VietnamNet":        _parse_vietnamnet,
    "BatDongSan":        _parse_batdongsan,
    "DanTri":            _parse_dantri,
    "TuoiTre":           _parse_tuoitre,
}


def scrape() -> list[dict]:
    keywords_cfg = load_keywords()
    sources_cfg  = load_sources()
    settings_cfg = load_settings()
    keywords = _all_keywords(keywords_cfg)
    negatives = _negative_keywords(keywords_cfg)
    delay = settings_cfg.get("scraping", {}).get("delay_between_requests", 2)

    all_results = []
    for site in sources_cfg.get("news_sites", []):
        name = site["name"]
        url = site["url"]
        parser_fn = _PARSERS.get(name)
        if not parser_fn:
            logger.warning("No parser for news site: %s", name)
            continue
        logger.info("Scraping %s (%s)", name, url)
        soup = _get_soup(url, delay)
        if soup is None:
            continue
        try:
            items = parser_fn(soup, url, keywords, negatives)
            logger.info("  → %d relevant articles from %s", len(items), name)
            all_results.extend(items)
        except Exception as exc:
            logger.error("Error parsing %s: %s", name, exc)

    return all_results


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    results = scrape()
    print(f"\nTotal relevant articles found: {len(results)}\n")
    for i, r in enumerate(results[:3], 1):
        print(f"--- Article {i} ---")
        print(f"Source  : {r['source']}")
        print(f"Title   : {r['title']}")
        print(f"Summary : {r['summary'][:120]}..." if len(r['summary']) > 120 else f"Summary : {r['summary']}")
        print(f"URL     : {r['url']}")
        print(f"Scraped : {r['scraped_at']}")
        print()
