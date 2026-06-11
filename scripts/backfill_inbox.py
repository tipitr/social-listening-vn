"""One-time deep backfill of the Facebook page inbox.

Walks every conversation active in the lookback window (default 365 days),
pages block-by-block into long threads, keeps home-loan messages (masked +
anonymized), stores them, then categorizes/translates the new ones.

Safe to re-run: messages dedupe on fb_message_id, so an interrupted backfill
resumes where it left off.

    python scripts/backfill_inbox.py            # 365 days
    python scripts/backfill_inbox.py 180        # custom lookback (days)
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")

from pipeline import db
from pipeline.collector import save_messages
from pipeline.categorizer import run_inbox
from scrapers.facebook_inbox import scrape

if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 365
    db.init_schema()

    logging.info("=== INBOX BACKFILL START — last %d days ===", days)
    messages = scrape(deep=True, lookback_days=days, max_calls=12000)
    inserted = save_messages(messages)
    logging.info("Backfill found %d relevant messages, %d new to the DB.",
                 len(messages), inserted)

    if inserted:
        logging.info("Categorizing + translating %d new messages…", inserted)
        run_inbox()

    with db.connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM inbox_messages").fetchone()[0]
    logging.info("=== BACKFILL DONE — %s total home-loan messages in DB ===",
                 dict(total=total) if not isinstance(total, int) else total)
