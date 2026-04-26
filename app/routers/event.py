import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.models.event import Event
from db.dependencies import get_db
from schemas.event import EventCreate, EventResponse

router = APIRouter()


@router.get("", response_model=list[EventResponse])
def list_events(
    q: Annotated[str | None, Query()] = None,
    db: Session = Depends(get_db),
) -> list[EventResponse]:
    events = db.query(Event).order_by(Event.created_at.desc()).all()

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
    event = Event(
        id=uuid.uuid4(),
        title=payload.title,
        description=payload.description,
        date=payload.date,
        cost=payload.cost,
        location=payload.location,
        category=payload.category,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event
