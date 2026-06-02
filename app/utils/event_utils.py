from datetime import date, datetime
from typing import Any
from sqlalchemy.orm import Session
from app.models.event import Event
from app.utils.geocoding import geocode_address
from schemas.event import HydratedEventResponse


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [tag.strip() for tag in value.split(",") if tag.strip()]


def enforce_coordinates_for_ingestion(values: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Ensure an event payload has geocoded coordinates before DB write.

    Returns (values, None) when coordinates are present/resolved.
    Returns (None, reason) when the row should be skipped.
    """
    location = values.get("location")
    if not location:
        return None, "missing location"

    lat = values.get("latitude")
    lng = values.get("longitude")
    if lat is None or lng is None:
        lat, lng = geocode_address(location)

    if lat is None or lng is None:
        return None, "geocode failed"

    values["latitude"] = lat
    values["longitude"] = lng
    return values, None


def is_event_active(event_date: datetime, today: date | None = None) -> bool:
    return event_date.date() >= (today or date.today())


def event_to_hydrated(event: Event, score: float | None = None) -> HydratedEventResponse:
    # latitude/longitude/end_time/image_url are not yet stored on the Event model.
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
        latitude=None,
        longitude=None,
        price_min=event.cost,
        price_max=event.cost,
        start_time=event.date.isoformat() if event.date else None,
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
