from __future__ import annotations

from datetime import datetime, timedelta, timezone

EAST_8 = timezone(timedelta(hours=8), "UTC+08:00")


def today_east8(now: datetime | None = None) -> str:
    """Return the calendar date in UTC+08:00 as YYYY-MM-DD."""
    current = now or datetime.now(EAST_8)
    return current.astimezone(EAST_8).strftime("%Y-%m-%d")
