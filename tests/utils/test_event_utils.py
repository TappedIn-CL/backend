from datetime import date, datetime

from app.utils.event_utils import is_event_active


def test_is_event_active_returns_true_for_today_and_future():
    today = date(2026, 5, 21)
    assert is_event_active(datetime(2026, 5, 21, 0, 0), today=today)
    assert is_event_active(datetime(2026, 5, 22, 9, 0), today=today)


def test_is_event_active_returns_false_for_past_date():
    today = date(2026, 5, 21)
    assert not is_event_active(datetime(2026, 5, 20, 23, 59), today=today)