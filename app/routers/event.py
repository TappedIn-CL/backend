import uuid
from datetime import date, datetime, time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.models.event import Event
from db.dependencies import get_db
from schemas.event import EventCreate, EventResponse
from app.utils.geocoding import geocode_address

router = APIRouter()


@router.get("", response_model=list[EventResponse])
def list_events(
    q: Annotated[str | None, Query()] = None,
    db: Session = Depends(get_db),
) -> list[EventResponse]:
    today_start = datetime.combine(date.today(), time.min)
    events = db.query(Event).filter(Event.date >= today_start).order_by(Event.date.asc()).all()

    if q and q.strip():
        query = q.strip().casefold()
        events = [
            e for e in events
            if query in " ".join(
                v for v in (e.title, e.description, e.location, e.category) if v
            ).casefold()
        ]

    return events


@router.get("/{event_id}", response_model=EventResponse)
def get_event(event_id: uuid.UUID, db: Annotated[Session, Depends(get_db)]) -> EventResponse:
    event = db.query(Event).filter(Event.id == event_id).first()
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.post("", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
def create_event(payload: EventCreate, db: Annotated[Session, Depends(get_db)]) -> EventResponse:
    # Convert lists to comma-separated strings for storage
    special_tags_str = ",".join(payload.special_tags) if payload.special_tags else None
    vibe_tags_str = ",".join(payload.vibe_tags) if payload.vibe_tags else None
    
    # If client didn't provide coordinates but provided a location string, try geocoding
    lat = payload.latitude
    lng = payload.longitude
    if (lat is None or lng is None) and payload.location:
        g_lat, g_lng = geocode_address(payload.location)
        if g_lat is not None and g_lng is not None:
            lat, lng = g_lat, g_lng

    event = Event(
        id=uuid.uuid4(),
        title=payload.title,
        description=payload.description,
        date=payload.date,
        cost=payload.cost,
        location=payload.location,
        latitude=lat,
        longitude=lng,
        category=payload.category,
        special_tags=special_tags_str,
        vibe_tags=vibe_tags_str,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event
