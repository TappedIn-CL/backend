"""Popular events feed: upcoming events ranked by save count.

Queries user_favorites at request time (no denormalized counter on events).
Falls back to soonest upcoming events when nothing has been saved yet.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from agent.recommendations import _fetch_recent_events, _to_event_schema
from agent.state import EventSchema
from app.models.event import Event
from app.models.favorite import UserFavorite
from app.utils.event_utils import event_to_hydrated

logger = logging.getLogger(__name__)


def _fetch_popular_events(db: Session, limit: int) -> list[tuple[Event, int]]:
    """Upcoming active events with the most saves, highest first."""
    now = datetime.utcnow()
    rows = (
        db.query(Event, func.count(UserFavorite.user_id).label("saves"))
        .join(UserFavorite, UserFavorite.event_id == Event.id)
        .filter(Event.is_active == True)  # noqa: E712
        .filter(Event.date >= now)
        .group_by(Event.id)
        .order_by(func.count(UserFavorite.user_id).desc(), Event.date.asc())
        .limit(limit)
        .all()
    )
    return [(event, int(saves)) for event, saves in rows]


def _to_scored_schemas(rows: list[tuple[Event, int]]) -> list[EventSchema]:
    if not rows:
        return []
    max_saves = max(saves for _, saves in rows) or 1
    out: list[EventSchema] = []
    for event, saves in rows:
        schema = _to_event_schema(event_to_hydrated(event))
        out.append({**schema, "score": saves / max_saves})
    return out


async def popular_events(db: Session, limit: int = 20) -> list[EventSchema]:
    """Return top upcoming events by global save count.

    score is normalized 0–1 (saves / max saves in result set) for frontend
    display via hydratedToDbEvent. Recency fallback omits score, matching
    For You cold-start behavior.
    """
    rows = await asyncio.to_thread(_fetch_popular_events, db, limit)
    if rows:
        return _to_scored_schemas(rows)

    logger.info("popular_events: no saved upcoming events, using recency fallback")
    recent = await asyncio.to_thread(_fetch_recent_events, db, limit, set())
    return [_to_event_schema(event_to_hydrated(r)) for r in recent]
