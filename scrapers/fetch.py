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
