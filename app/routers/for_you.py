import asyncio
import uuid
import logging
from datetime import date, datetime, time
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from agent.scoring import compute_taste_vector
from agent.pinecone_client import search_events
from app.models.event import Event
from app.utils.event_utils import event_to_hydrated
from db.dependencies import get_db
from schemas.event import HydratedEventResponse

router = APIRouter()
logger = logging.getLogger(__name__)

RECOMMENDATION_LIMIT = 20


def _fallback_events(db: Session, limit: int) -> list[HydratedEventResponse]:
    """Upcoming events by date — used when no taste signal is available."""
    today_start = datetime.combine(date.today(), time.min)
    events = (
        db.query(Event)
        .filter(Event.date >= today_start, Event.is_active == True)
        .order_by(Event.date.asc())
        .limit(limit)
        .all()
    )
    return [event_to_hydrated(e) for e in events]


def _tags_from_favorite_events(
    db: Session, fav_id_strings: list[str]
) -> list[str]:
    """
    Fetch the category and vibe_tags from the user's favorited events.
    These become the 'favorited_tags' signal in compute_taste_vector.
    """
    parsed_uuids = []
    for s in fav_id_strings:
        try:
            parsed_uuids.append(uuid.UUID(s))
        except ValueError:
            pass
    if not parsed_uuids:
        return []

    events = db.query(Event).filter(Event.id.in_(parsed_uuids)).all()
    tags: list[str] = []
    for e in events:
        if e.category:
            tags.append(e.category)
        if e.vibe_tags:
            tags.extend(t.strip() for t in e.vibe_tags.split(",") if t.strip())
    return tags


@router.get("", response_model=list[HydratedEventResponse])
async def get_for_you(
    interests: Annotated[
        str | None,
        Query(description="Comma-separated user interests, e.g. 'Music,Nightlife'"),
    ] = None,
    favorite_ids: Annotated[
        str | None,
        Query(description="Comma-separated favorited event UUIDs"),
    ] = None,
    db: Session = Depends(get_db),
) -> list[HydratedEventResponse]:
    """
    Returns personalised event recommendations.

    Accepts interests and favorite event IDs as query params from the frontend
    (read from AuthContext + FavoritesContext) so no JWT verification is needed.

    Taste vector = embed(interests + tags extracted from favorited events).
    Falls back to upcoming events when there is no taste signal.
    """
    interest_list = (
        [i.strip() for i in interests.split(",") if i.strip()] if interests else []
    )
    fav_id_list = (
        [i.strip() for i in favorite_ids.split(",") if i.strip()] if favorite_ids else []
    )

    # Derive tags from the user's favorited events (category + vibe_tags)
    favorited_tags = _tags_from_favorite_events(db, fav_id_list)

    if not interest_list and not favorited_tags:
        return _fallback_events(db, RECOMMENDATION_LIMIT)

    try:
        taste_vector = await asyncio.to_thread(
            compute_taste_vector, interest_list, favorited_tags
        )
    except Exception as e:
        logger.warning("Taste vector computation failed: %s — falling back", e)
        return _fallback_events(db, RECOMMENDATION_LIMIT)

    if taste_vector is None:
        return _fallback_events(db, RECOMMENDATION_LIMIT)

    try:
        matches = await asyncio.to_thread(
            search_events, taste_vector, {}, RECOMMENDATION_LIMIT * 2
        )
    except Exception as e:
        logger.warning("Pinecone search failed: %s — falling back", e)
        return _fallback_events(db, RECOMMENDATION_LIMIT)

    # Dedup by title — same event can have multiple Pinecone records from re-scrapes
    seen_titles: set[str] = set()
    event_ids: list[uuid.UUID] = []
    for m in matches:
        title = m["metadata"].get("title", "").strip().lower()
        if not title or title in seen_titles:
            continue
        seen_titles.add(title)
        try:
            event_ids.append(uuid.UUID(m["id"]))
        except ValueError:
            continue
        if len(event_ids) >= RECOMMENDATION_LIMIT:
            break

    if not event_ids:
        return _fallback_events(db, RECOMMENDATION_LIMIT)

    events = db.query(Event).filter(Event.id.in_(event_ids)).all()
    by_id = {e.id: e for e in events}
    # Preserve Pinecone ranking order
    return [event_to_hydrated(by_id[eid]) for eid in event_ids if eid in by_id]
