"""For You Page: query-less personalized event recommendations.

Pipeline:
  1. Build taste vector from user_profile (interests/vibes/favorited events).
  2. If no taste signal at all → recency fallback (cold-start safety net).
  3. Otherwise, search Pinecone with the taste vector, apply demographic
     hard filters, dedupe by title, exclude already-favorited events.
  4. Hydrate via Supabase, rank by cosine(taste, event), return top-K.

Lives outside the LangGraph topology because the For You feed has no query
intent to parse — it's pure taste retrieval, not search.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from agent.pinecone_client import fetch_vectors, search_events
from agent.scoring import compute_taste_vector, cosine_similarity
from agent.state import EventSchema
from app.models.event import Event
from app.models.favorite import UserFavorite
from app.utils.event_utils import event_to_hydrated
from db.dependencies import get_db

logger = logging.getLogger(__name__)

# Over-fetch from Pinecone to leave room for dedup + favorite exclusion.
PINECONE_OVERFETCH = 3


def _to_event_schema(hydrated) -> EventSchema:
    """Cast HydratedEventResponse → EventSchema dict for ranking. The
    ranking layer treats EventSchema as the contract; mirror its shape."""
    return {
        "id": str(hydrated.id),
        "title": hydrated.title,
        "description": hydrated.description or "",
        "category": hydrated.category or "",
        "tags": hydrated.tags or [],
        "vibe_tags": hydrated.vibe_tags or [],
        "venue_name": hydrated.venue_name or "",
        "address": hydrated.address or "",
        "city": hydrated.city or "Los Angeles",
        "latitude": hydrated.latitude or 0.0,
        "longitude": hydrated.longitude or 0.0,
        "price_min": hydrated.price_min or 0.0,
        "price_max": hydrated.price_max or 0.0,
        "start_time": hydrated.start_time or "",
        "end_time": hydrated.end_time,
        "image_url": hydrated.image_url,
        "source_url": hydrated.source_url or "",
    }


def _build_taste_vector_sync(user_profile: dict) -> list[float] | None:
    interests = user_profile.get("interests") or []
    vibes = user_profile.get("vibes") or []
    favorited_tags = user_profile.get("favorited_tags") or []
    favorited_event_ids = user_profile.get("favorited_event_ids") or []

    favorited_event_vectors: list[list[float]] = []
    if favorited_event_ids:
        try:
            vectors_by_id = fetch_vectors(favorited_event_ids)
            favorited_event_vectors = list(vectors_by_id.values())
        except Exception as e:
            logger.warning(
                "recommend_for_you: failed to fetch favorite vectors: %s", e
            )

    return compute_taste_vector(
        interests=interests,
        favorited_tags=favorited_tags,
        vibes=vibes,
        favorited_event_vectors=favorited_event_vectors,
    )


def _build_pinecone_filter(user_profile: dict) -> dict:
    """Demographic hard filters. Lenient — only adds constraints that the
    Pinecone metadata actually supports (price_max, city)."""
    f: dict = {}
    price_max = user_profile.get("price_max")
    if price_max is not None:
        f["price_max"] = {"$lte": float(price_max)}
    return f


def _fetch_recent_events(db: Session, limit: int, exclude_ids: set[str]) -> list[Event]:
    """Cold-start fallback. Future events, soonest first."""
    now = datetime.utcnow()
    query = (
        db.query(Event)
        .filter(Event.date >= now)
        .filter(Event.is_active == True)  # noqa: E712 — SQLAlchemy comparator
        .order_by(Event.date.asc())
    )
    if exclude_ids:
        from uuid import UUID
        try:
            excluded = [UUID(i) for i in exclude_ids]
            query = query.filter(~Event.id.in_(excluded))
        except (TypeError, ValueError):
            logger.warning("recommend_for_you: invalid favorite UUID in exclude set")
    return query.limit(limit).all()


def _hydrate_from_db(db: Session, event_ids: list[str]) -> list[EventSchema]:
    """Load events from Supabase in the original Pinecone-ranked order.

    Same-process DB access — no httpx loopback. Silently skips non-UUID IDs
    (legacy mocks) and Pinecone-only orphans, matching /events/by-ids.
    """
    if not event_ids:
        return []

    from uuid import UUID

    parsed: list[tuple[str, UUID]] = []
    for i in event_ids:
        try:
            parsed.append((i, UUID(i)))
        except (TypeError, ValueError):
            continue
    if not parsed:
        return []

    uuid_list = [p[1] for p in parsed]
    rows = (
        db.query(Event)
        .filter(Event.id.in_(uuid_list))
        .filter(Event.is_active == True)  # noqa: E712
        .filter(Event.date >= datetime.utcnow())
        .all()
    )
    by_id = {e.id: e for e in rows}

    out: list[EventSchema] = []
    for raw, parsed_id in parsed:
        row = by_id.get(parsed_id)
        if row is None:
            continue
        out.append(_to_event_schema(event_to_hydrated(row)))
    return out


async def recommend_for_you(
    user_profile: dict,
    db: Session,
    limit: int = 20,
) -> list[EventSchema]:
    """Build a personalized event feed for the user.

    Cold-start (no taste signal at all): returns soonest upcoming events,
    minus already-favorited ones. Never returns an empty list when events
    exist in Supabase.
    """
    exclude_ids = set(user_profile.get("favorited_event_ids") or [])

    taste_vector = await asyncio.to_thread(_build_taste_vector_sync, user_profile)

    if taste_vector is None:
        logger.info("recommend_for_you: cold-start, using recency fallback")
        rows = await asyncio.to_thread(
            _fetch_recent_events, db, limit, exclude_ids
        )
        return [_to_event_schema(event_to_hydrated(r)) for r in rows]

    pinecone_filter = _build_pinecone_filter(user_profile)
    top_k = max(limit * PINECONE_OVERFETCH, limit + len(exclude_ids))

    try:
        matches = await asyncio.to_thread(
            search_events, taste_vector, pinecone_filter, top_k
        )
    except Exception as e:
        logger.error("recommend_for_you: Pinecone search failed: %s", e)
        # On Pinecone failure, fall back to recency so the page still loads.
        rows = await asyncio.to_thread(
            _fetch_recent_events, db, limit, exclude_ids
        )
        return [_to_event_schema(event_to_hydrated(r)) for r in rows]

    # Dedup by title (same logic as retrieve_events) + exclude favorites.
    candidate_ids: list[str] = []
    seen_titles: set[str] = set()
    for m in matches:
        if m["id"] in exclude_ids:
            continue
        title = (m["metadata"].get("title") or "").strip().lower()
        if not title or title in seen_titles:
            continue
        seen_titles.add(title)
        candidate_ids.append(m["id"])
        if len(candidate_ids) >= limit:
            break

    if not candidate_ids:
        return []

    hydrated = await asyncio.to_thread(_hydrate_from_db, db, candidate_ids)
    if not hydrated:
        return []

    # Rank by pure taste cosine. event_vectors come from Pinecone fetch;
    # any candidate missing from Pinecone after the search is dropped.
    try:
        event_vectors = await asyncio.to_thread(
            fetch_vectors, [e["id"] for e in hydrated]
        )
    except Exception as e:
        logger.error("recommend_for_you: vector fetch for ranking failed: %s", e)
        # Preserve Pinecone's search-order ranking.
        return hydrated[:limit]

    scored: list[tuple[float, EventSchema]] = []
    for event in hydrated:
        ev = event_vectors.get(event["id"])
        if ev is None:
            continue
        scored.append((cosine_similarity(taste_vector, ev), event))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [{**event, "score": score} for score, event in scored][:limit]
