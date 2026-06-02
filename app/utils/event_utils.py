from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.models.event import Event
from schemas.event import HydratedEventResponse


# Default event length when a source doesn't supply an end time. `date`/`end_time`
# are stored as naive Los Angeles wall-clock times, so adding a timedelta stays
# LA-local (no tz conversion needed). Matches run_cleanup.GRACE_HOURS.
DEFAULT_EVENT_DURATION_HOURS = 3


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [tag.strip() for tag in value.split(",") if tag.strip()]


def effective_end_time(event: Event) -> datetime | None:
    """Stored end_time if the source gave one, else start + DEFAULT_EVENT_DURATION_HOURS."""
    if event.end_time:
        return event.end_time
    if event.date:
        return event.date + timedelta(hours=DEFAULT_EVENT_DURATION_HOURS)
    return None


def event_to_hydrated(event: Event, score: float | None = None) -> HydratedEventResponse:
    # latitude/longitude/image_url are demo placeholders — the Event model
    # doesn't store them yet. The frontend tolerates None.
    # end_time defaults to start + 3h via effective_end_time when not stored.
    # venue_name and address both map from `location` for the demo.
    end_time = effective_end_time(event)
    return HydratedEventResponse(
        id=event.id,
        title=event.title,
        description=event.description,
        category=event.category,
        tags=_split_csv(event.special_tags),
        vibe_tags=_split_csv(event.vibe_tags),
        venue_name=event.location,
        address=event.location,
        city="Los Angeles",
        latitude=None,
        longitude=None,
        price_min=event.cost,
        price_max=event.cost,
        start_time=event.date.isoformat() if event.date else None,
        end_time=end_time.isoformat() if end_time else None,
        image_url=None,
        source_url=event.source_url,
        score=score,
    )


def deactivate_past_events(db: Session) -> int:
    """
    Mark events as inactive if their start date has passed.
    Returns the number of events deactivated.
    """
    now = datetime.utcnow()
    past_events = db.query(Event).filter(
        Event.date < now,
        Event.is_active == True
    ).all()

    count = 0
    for event in past_events:
        event.is_active = False
        count += 1

    if count > 0:
        db.commit()

    return count
