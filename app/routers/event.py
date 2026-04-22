from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, HTTPException, status

from schemas.event import EventCreate, EventResponse

router = APIRouter()

_mock_events: dict[uuid.UUID, EventResponse] = {}

for event in [
    EventResponse(
        id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        title="Dozy Cafe",
        description="UCLA matcha pop-up",
        date=datetime(2026, 4, 24, 18, 30, tzinfo=timezone.utc),
        cost=6.5,
        location="UCLA",
        category="Food & Drink",
        created_at=datetime(2026, 4, 20, 8, 0, tzinfo=timezone.utc),
    ),
    EventResponse(
        id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        title="Indie Film Night",
        description="Community screening and Q&A.",
        date=datetime(2026, 4, 27, 19, 0, tzinfo=timezone.utc),
        cost=8.5,
        location="Cinema One",
        category="Arts",
        created_at=datetime(2026, 4, 20, 8, 5, tzinfo=timezone.utc),
    ),
        EventResponse(
        id=uuid.UUID("33333333-3333-3333-3333-333333333333"),
        title="LA fashion pop-up",
        description="buy tuff fits",
        date=datetime(2026, 5, 1, 19, 0, tzinfo=timezone.utc),
        cost=9,
        location="Westwood",
        category="Fashion",
        created_at=datetime(2026, 4, 27, 8, 5, tzinfo=timezone.utc),
    ),
]:
    _mock_events[event.id] = event


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
