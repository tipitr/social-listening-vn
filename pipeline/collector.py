"""Collect scraper results and persist them to the database."""

import logging
from pathlib import Path

from dotenv import load_dotenv

from pipeline import db
from pipeline.config_loader import load_settings
from pipeline.timeutils import days_ago_iso, now_iso

load_dotenv(override=True)  # see pipeline/categorizer.py for rationale

logger = logging.getLogger(__name__)

# Re-exported for callers that import collector.DB_PATH (legacy convenience —
# only meaningful when running on SQLite).
DB_PATH = db.SQLITE_PATH

# INSERT ... ON CONFLICT DO NOTHING works in both Postgres and SQLite 3.24+,
# so the same statement runs against either backend.
_INSERT = """
INSERT INTO articles
    (source, source_url, title, summary, url, category, scraped_at, created_at)
VALUES
    (:source, :source_url, :title, :summary, :url, :category, :scraped_at, :created_at)
ON CONFLICT (url) DO NOTHING;
"""


def init_db() -> None:
    """Create tables on first run and apply any column migrations. Idempotent."""
    db.init_schema()
    logger.info("Database ready (%s)", db.backend_name())


def log_usage(service: str, model: str = "", tokens_in: int = 0,
              tokens_out: int = 0, cost_usd: float = 0.0, items_processed: int = 0) -> None:
    """Record an API call to the usage_log table."""
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO usage_log "
            "(service, model, tokens_in, tokens_out, cost_usd, items_processed, created_at) "
            "VALUES (:service, :model, :tokens_in, :tokens_out, :cost_usd, :items_processed, :created_at)",
            {
                "service": service, "model": model,
                "tokens_in": tokens_in, "tokens_out": tokens_out,
                "cost_usd": round(cost_usd, 6),
                "items_processed": items_processed,
                "created_at": now_iso(),
            },
        )


def save(articles: list[dict]) -> int:
    """Insert articles, skip duplicates (by URL). Returns count of new rows."""
    if not articles:
        return 0

    now = now_iso()
    rows = [
        {
            "source":     a.get("source", ""),
            "source_url": a.get("source_url", ""),
            "title":      a.get("title", ""),
            "summary":    a.get("summary", ""),
            "url":        a.get("url", ""),
            "category":   a.get("category"),
            "scraped_at": a.get("scraped_at", now),
            "created_at": now,
        }
        for a in articles
    ]

    with db.connect() as conn:
        cursor = conn.executemany(_INSERT, rows)
        # SQLite reports rowcount of inserts here; Postgres reports the
        # same for INSERT ... ON CONFLICT DO NOTHING.
        inserted = cursor.rowcount if cursor.rowcount >= 0 else len(rows)

    logger.info("Saved %d new articles (skipped %d duplicates)", inserted, len(rows) - inserted)
    return inserted


def fetch_recent(days: int = 7) -> list[dict]:
    """Return articles from the last N days (GMT+7), newest first."""
    sql = """
        SELECT * FROM articles
        WHERE scraped_at >= :cutoff
        ORDER BY scraped_at DESC
    """
    with db.connect() as conn:
        rows = conn.execute(sql, {"cutoff": days_ago_iso(days)}).fetchall()
    return [dict(r) for r in rows]


def collect_all() -> int:
    """Run all scrapers and save to DB. Returns total inserted.

    Uses smart_scraper: requests/BS4 first, Firecrawl fallback for blocked/JS sites.
    Falls back to plain requests-only if FIRECRAWL_API_KEY is not set.
    """
    import os

    init_db()

    if os.getenv("FIRECRAWL_API_KEY"):
        from scrapers.smart_scraper import scrape as scrape_smart
        articles = scrape_smart()
    else:
        from scrapers.news import scrape as scrape_news
        from scrapers.forums import scrape as scrape_forums
        articles = scrape_news() + scrape_forums()

    # Two Facebook backends — pick whichever has credentials.
    # Meta Graph API is the canonical path but App ID + Secret review can take
    # weeks. RapidAPI "Facebook Scraper3" is the bridge — same output shape,
    # 5-minute setup. If both are set, the Meta one wins (more reliable).
    if os.getenv("FACEBOOK_ACCESS_TOKEN") or os.getenv("FACEBOOK_APP_ID"):
        from scrapers.facebook import scrape as scrape_facebook
        articles += scrape_facebook()
    elif os.getenv("RAPIDAPI_KEY"):
        from scrapers.facebook_scraper3 import scrape as scrape_facebook_rapid
        articles += scrape_facebook_rapid()

    inserted = save(articles)

    # Log every run (even zero-insert ones) so the dashboard can show whether
    # the daily schedule is alive. Otherwise a healthy-but-quiet day looks
    # identical to a broken cron.
    try:
        log_usage("scrape_run", items_processed=inserted)
    except Exception as exc:
        logger.warning("Could not log scrape_run heartbeat: %s", exc)

    # Always categorize immediately so articles are never stranded without labels
    if inserted > 0:
        try:
            from pipeline.categorizer import run as categorize
            categorize()
        except Exception as exc:
            logger.error("Categorizer failed after collect: %s", exc)

    return inserted


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    inserted = collect_all()

    print(f"\nInserted {inserted} new articles (backend: {db.backend_name()})")

    recent = fetch_recent(days=7)
    print(f"Total in DB (last 7 days): {len(recent)}")
    for r in recent[:3]:
        print(f"  [{r['source']}] {r['title'][:80]}")
