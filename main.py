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

    inserted = collect_all()
    logger.info("Collected %d new articles", inserted)

    if inserted == 0:
        # collect_all only categorizes when new rows landed — sweep up any stragglers
        categorize()

    logger.info("=== Pipeline complete ===")
