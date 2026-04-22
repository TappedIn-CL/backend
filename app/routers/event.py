from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, HTTPException, status

from schemas.event import EventCreate, EventResponse

router = APIRouter()

_mock_events: dict[uuid.UUID, EventResponse] = {}


@router.get("", response_model=list[EventResponse])
def list_events() -> list[EventResponse]:
    return list(_mock_events.values())


@router.get("/{event_id}", response_model=EventResponse)
def get_event(event_id: uuid.UUID) -> EventResponse:
    event = _mock_events.get(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.post("", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
def create_event(payload: EventCreate) -> EventResponse:
    event = EventResponse(
        id=uuid.uuid4(),
        title=payload.title,
        description=payload.description,
        date=payload.date,
        cost=payload.cost,
        location=payload.location,
        category=payload.category,
        created_at=datetime.now(timezone.utc),
    )
    _mock_events[event.id] = event
    return event
