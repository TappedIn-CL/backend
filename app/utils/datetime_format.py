from datetime import datetime, timezone


def format_stored_event_datetime(dt: datetime | None) -> str | None:
    """Serialize a DB event timestamp for API clients.

    Scraped event times are stored as naive UTC in Postgres. Append ``Z`` so
    browsers parse them as UTC and convert to the user's local timezone.
    """
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    iso = dt.isoformat(timespec="seconds")
    return iso if iso.endswith("Z") else f"{iso}Z"
