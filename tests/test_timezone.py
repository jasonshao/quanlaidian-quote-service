from datetime import datetime, timezone

from app.timezone import today_east8


def test_today_east8_converts_utc_to_next_calendar_day():
    assert (
        today_east8(datetime(2026, 5, 7, 16, 30, tzinfo=timezone.utc))
        == "2026-05-08"
    )
