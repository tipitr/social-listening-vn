"""Time helpers — project standardised on Asia/Ho_Chi_Minh (GMT+7).

All written timestamps (scraped_at, created_at, report filenames) and all
SQL date-window comparisons should go through this module so the dashboard
and reports show times that match the team's wall clock in Vietnam.
"""

from datetime import datetime, timedelta, timezone

LOCAL_TZ = timezone(timedelta(hours=7), name="Asia/Ho_Chi_Minh")


def now_local() -> datetime:
    """Current local time as a naive datetime (no tzinfo).

    We strip tzinfo so the ISO strings stored in SQLite stay lexically
    sortable alongside SQLite's `datetime('now', '+7 hours')`.
    """
    return datetime.now(LOCAL_TZ).replace(tzinfo=None)


def now_iso() -> str:
    """ISO-formatted local timestamp for DB writes."""
    return now_local().isoformat()


def days_ago_iso(days: int) -> str:
    """ISO timestamp for N days before now_local() — pass to SQL parameters."""
    return (now_local() - timedelta(days=days)).isoformat()
