from datetime import datetime
from sqlalchemy.orm import Session
from app.models.event import Event
from app.utils.datetime_format import format_stored_event_datetime
from schemas.event import HydratedEventResponse


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [tag.strip() for tag in value.split(",") if tag.strip()]


def event_to_hydrated(event: Event, score: float | None = None) -> HydratedEventResponse:
    # venue_name and address both map from `location` for the demo.
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
        latitude=event.latitude,
        longitude=event.longitude,
        price_min=event.cost,
        price_max=event.cost,
        start_time=format_stored_event_datetime(event.date),
        end_time=None,
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
