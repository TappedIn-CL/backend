from datetime import datetime, timezone

from app.utils.datetime_format import format_stored_event_datetime


def test_format_stored_event_datetime_naive_appends_z():
    dt = datetime(2026, 6, 3, 2, 0, 0)
    assert format_stored_event_datetime(dt) == "2026-06-03T02:00:00Z"


def test_format_stored_event_datetime_aware_converts_to_utc():
    dt = datetime(2026, 6, 2, 19, 0, 0, tzinfo=timezone.utc)
    assert format_stored_event_datetime(dt) == "2026-06-02T19:00:00Z"


def test_format_stored_event_datetime_none():
    assert format_stored_event_datetime(None) is None
