"""TDD for fix #8: when the scheduled pipeline crashes, write a failure
heartbeat to usage_log so the dashboard can surface it immediately.

ROOT CAUSE (from audit): pipeline/scheduler.py:43 catches collector
exceptions and logs to stdout. Nothing reaches the DB, so the dashboard
"stale data" banner takes 24h to flip. Operations are flying blind.

EXPECTED BEHAVIOR after fix:
  - collector raises → write usage_log row with service='scrape_failed'
    and an error excerpt in `model` or similar field we can show later.
  - categorizer raises → same.
  - happy path is unchanged (no spurious failure rows).

We test by patching collect_all/categorize and inspecting log_usage calls.
"""

from __future__ import annotations

from unittest.mock import patch, call

import pytest


def test_scheduler_logs_scrape_failed_when_collector_raises():
    """If collect_all() raises, scheduler must log a 'scrape_failed' heartbeat."""
    from pipeline import scheduler

    logged = []

    def fake_log_usage(service, model="", **kwargs):
        logged.append({"service": service, "model": model, **kwargs})

    with patch("pipeline.collector.collect_all", side_effect=RuntimeError("boom")), \
         patch("pipeline.collector.log_usage", side_effect=fake_log_usage):
        scheduler.run_pipeline()

    services = [row["service"] for row in logged]
    assert "scrape_failed" in services, (
        f"Expected a 'scrape_failed' usage_log row after collector exception. "
        f"Got services: {services}"
    )
    # The exception message should appear in the row so we can surface it.
    failed_row = next(r for r in logged if r["service"] == "scrape_failed")
    combined = " ".join(str(v) for v in failed_row.values())
    assert "boom" in combined, (
        f"The exception message should be captured in the heartbeat row. Got: {failed_row}"
    )


def test_scheduler_does_not_log_failure_on_happy_path():
    """No spurious 'scrape_failed' row when collector + categorizer succeed."""
    from pipeline import scheduler

    logged = []

    def fake_log_usage(service, model="", **kwargs):
        logged.append({"service": service, "model": model, **kwargs})

    with patch("pipeline.collector.collect_all", return_value=5), \
         patch("pipeline.categorizer.run", return_value=5), \
         patch("pipeline.collector.log_usage", side_effect=fake_log_usage):
        scheduler.run_pipeline()

    services = [row["service"] for row in logged]
    assert "scrape_failed" not in services, (
        f"Happy path should not write a failure heartbeat. Got: {services}"
    )


def test_scheduler_logs_scrape_failed_when_categorizer_raises():
    """If categorize() raises, scheduler must log a failure heartbeat too."""
    from pipeline import scheduler

    logged = []

    def fake_log_usage(service, model="", **kwargs):
        logged.append({"service": service, "model": model, **kwargs})

    with patch("pipeline.collector.collect_all", return_value=3), \
         patch("pipeline.categorizer.run", side_effect=RuntimeError("cat-boom")), \
         patch("pipeline.collector.log_usage", side_effect=fake_log_usage):
        scheduler.run_pipeline()

    services = [row["service"] for row in logged]
    assert "scrape_failed" in services, (
        f"Categorizer failure should also produce a failure heartbeat. Got: {services}"
    )
