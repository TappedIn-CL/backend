"""Discovery feeds for the For You page rails that aren't taste-personalized:

- happening_today_events: events scheduled for the current LA calendar date
  (any hour of the day — Rohan's product call is "don't worry about hours")
- recently_posted_events: most recently scraped events (created_at desc),
  scoped to upcoming events only so the rail surfaces things users can attend
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from agent.recommendations import _to_event_schema
from agent.state import EventSchema
from app.models.event import Event
from app.utils.event_utils import event_to_hydrated

logger = logging.getLogger(__name__)

# Event date/end_time are stored as naive LA wall-clock per Allen's helpers.
# Compute today's window in LA-naive too so the comparison is apples-to-apples.
LOCAL_TZ = ZoneInfo("America/Los_Angeles")


def _today_window_la() -> tuple[datetime, datetime]:
    now_la = datetime.now(LOCAL_TZ).replace(tzinfo=None)
    today_start = now_la.replace(hour=0, minute=0, second=0, microsecond=0)
    return today_start, today_start + timedelta(days=1)


def _fetch_happening_today(db: Session, limit: int) -> list[Event]:
    today_start, tomorrow_start = _today_window_la()
    return (
        db.query(Event)
        .filter(Event.is_active == True)  # noqa: E712
        .filter(Event.date >= today_start)
        .filter(Event.date < tomorrow_start)
        .order_by(Event.date.asc())
        .limit(limit)
        .all()
    )


def _fetch_recently_posted(db: Session, limit: int) -> list[Event]:
    """Newest-first by created_at. Limited to upcoming events so the rail
    surfaces things you can still attend, not freshly-scraped past events."""
    now_la = datetime.now(LOCAL_TZ).replace(tzinfo=None)
    return (
        db.query(Event)
        .filter(Event.is_active == True)  # noqa: E712
        .filter(Event.date >= now_la)
        .order_by(Event.created_at.desc())
        .limit(limit)
        .all()
    )


async def happening_today_events(db: Session, limit: int = 20) -> list[EventSchema]:
    """Events scheduled for the current LA calendar date, soonest first."""
    rows = await asyncio.to_thread(_fetch_happening_today, db, limit)
    return [_to_event_schema(event_to_hydrated(e)) for e in rows]


async def recently_posted_events(db: Session, limit: int = 20) -> list[EventSchema]:
    """Most-recently-added upcoming events, newest-first by created_at."""
    rows = await asyncio.to_thread(_fetch_recently_posted, db, limit)
    return [_to_event_schema(event_to_hydrated(e)) for e in rows]
