"""Pipeline scheduler — runs collect + categorize at configured times."""

import logging
import sys
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

load_dotenv(override=True)  # see pipeline/categorizer.py for rationale

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


def _log_failure(stage: str, exc: Exception) -> None:
    """Write a 'scrape_failed' heartbeat to usage_log so the dashboard can
    surface a broken pipeline within minutes instead of 24 hours.

    We stash the stage + exception message in the `model` column (it's a free
    text field). The dashboard reads usage_log for the existing "last scrape"
    badge — once it knows about scrape_failed, it can flip to a red banner.
    """
    try:
        from pipeline.collector import log_usage
        # Truncate to 200 chars so a stack-trace-ish message doesn't blow up
        # the row width on Postgres.
        excerpt = f"{stage}: {exc}"[:200]
        log_usage("scrape_failed", model=excerpt)
    except Exception as log_exc:
        # If even the failure log fails, fall back to stdout so we don't mask
        # the original problem.
        logger.error("Could not record failure heartbeat: %s", log_exc)


def run_pipeline():
    logger.info("=== Daily pipeline starting ===")
    try:
        from pipeline.collector import collect_all
        inserted = collect_all()
        logger.info("Collector done — %d new articles", inserted)
    except Exception as exc:
        logger.error("Collector failed: %s", exc)
        _log_failure("collector", exc)
        return

    try:
        from pipeline.categorizer import run as categorize
        categorize()
        logger.info("Categorizer done")
    except Exception as exc:
        logger.error("Categorizer failed: %s", exc)
        _log_failure("categorizer", exc)

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
