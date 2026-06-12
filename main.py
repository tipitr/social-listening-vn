"""Entry point — collect + categorize in one shot.

`collect_all` already runs the categorizer after new rows are saved,
so this is a single call. We also run categorize again at the end to
catch any rows that were inserted earlier but never labelled
(e.g. an interrupted run).
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

from pipeline.collector import collect_all
from pipeline.categorizer import run as categorize

if __name__ == "__main__":
    logger.info("=== Pipeline starting ===")

    try:
        inserted = collect_all()
        logger.info("Collected %d new articles", inserted)

        if inserted == 0:
            # collect_all only categorizes when new rows landed — sweep up stragglers
            categorize()
    except Exception:
        # Individual scraper failures are already swallowed inside collect_all;
        # reaching here means the PIPELINE itself died (DB down, bad config).
        # Exit non-zero so the GitHub Actions run shows a red ✗ instead of a
        # green check over a silent failure.
        logger.exception("Pipeline failed")
        sys.exit(1)

    logger.info("=== Pipeline complete ===")
