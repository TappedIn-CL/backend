from datetime import date as date_cls
from datetime import datetime


def parse_event_datetime(date_value, time_value=None):
    normalized_date = str(date_value).replace("Z", "+00:00")
    event_date = datetime.fromisoformat(normalized_date)

    if time_value:
        try:
            parsed_time = datetime.strptime(time_value, "%I:%M %p")
            event_date = event_date.replace(hour=parsed_time.hour, minute=parsed_time.minute)
        except ValueError:
            pass

    return event_date


def is_current_or_future_event(event_date, today=None):
    return event_date.date() >= (today or date_cls.today())
