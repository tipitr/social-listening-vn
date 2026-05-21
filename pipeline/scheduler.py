"""Pipeline scheduler — runs collect + categorize at configured times."""

import logging
import sys
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.config_loader import load_settings  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def _load_schedule():
    cfg = load_settings()
    sched = cfg.get("schedule", {})
    timezone = sched.get("timezone", "Asia/Ho_Chi_Minh")
    # Support both old single run_time and new run_times list
    raw = sched.get("run_times") or [sched.get("run_time", "08:00")]
    times = []
    for t in raw:
        h, m = t.split(":")
        times.append((int(h), int(m)))
    return times, timezone


def run_pipeline():
    logger.info("=== Daily pipeline starting ===")
    try:
        from pipeline.collector import collect_all
        inserted = collect_all()
        logger.info("Collector done — %d new articles", inserted)
    except Exception as exc:
        logger.error("Collector failed: %s", exc)
        return

    try:
        from pipeline.categorizer import run as categorize
        categorize()
        logger.info("Categorizer done")
    except Exception as exc:
        logger.error("Categorizer failed: %s", exc)

    logger.info("=== Daily pipeline complete ===")


if __name__ == "__main__":
    times, timezone = _load_schedule()

    scheduler = BlockingScheduler(timezone=timezone)
    for i, (hour, minute) in enumerate(times):
        scheduler.add_job(
            run_pipeline,
            CronTrigger(hour=hour, minute=minute, timezone=timezone),
            id=f"pipeline_{i}",
            name=f"Pipeline at {hour:02d}:{minute:02d} {timezone}",
            misfire_grace_time=3600,
        )
        logger.info("Scheduled — pipeline runs daily at %02d:%02d %s", hour, minute, timezone)

    logger.info("Press Ctrl+C to stop")

    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Scheduler stopped")
