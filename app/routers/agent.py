import json
import time
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from agent.graph import agent
from app.services.popular import popular_events
from agent.recommendations import recommend_for_you
from auth.profile import get_user_profile_optional, get_user_profile_required
from db.dependencies import get_db
from schemas.agent import AgentQueryRequest

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/query")
async def agent_query(
    payload: AgentQueryRequest,
    user_profile: Annotated[dict | None, Depends(get_user_profile_optional)],
):
    async def event_generator():
        start_time = time.time()

        yield "event: phase\ndata: {\"phase\": \"parsing\"}\n\n"

        try:
            async for event in agent.astream({
                "query": payload.query,
                "chips": payload.chips,
                "user_profile": user_profile,
                "semantic_query": "",
                "filters": {},
                "query_vector": None,
                "candidate_events": [],
                "hydrated_events": [],
                "ranked_events": [],
                "response": None,
                "taste_vector": None,
            }):
                if "parse_intent" in event:
                    yield "event: phase\ndata: {\"phase\": \"retrieving\"}\n\n"
                elif "retrieve_events" in event:
                    yield "event: phase\ndata: {\"phase\": \"hydrating\"}\n\n"
                elif "hydrate_events" in event:
                    yield "event: phase\ndata: {\"phase\": \"scoring\"}\n\n"
                elif "score_and_rank" in event:
                    state = event["score_and_rank"]
                    latency = int((time.time() - start_time) * 1000)
                    results = {
                        "events": state.get("ranked_events", []),
                        "count": len(state.get("ranked_events", [])),
                        "latency_ms": latency,
                    }
                    yield f"event: results\ndata: {json.dumps(results)}\n\n"
                    yield "event: done\ndata: {}\n\n"

        except Exception as e:
            logger.error("Agent query failed: %s", e)
            yield f"event: error\ndata: {json.dumps({'detail': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/for-you")
async def for_you(
    user_profile: Annotated[dict, Depends(get_user_profile_required)],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
):
    """Query-less personalized event feed.

    Builds a taste vector from the user's interests, vibes, and past
    favorited event vectors, then ranks candidates by taste similarity.
    Excludes already-favorited events. Cold-start users (no signals) get a
    recency-ordered fallback so the page is never empty.
    """
    start_time = time.time()
    events = await recommend_for_you(user_profile, db, limit=limit)
    latency_ms = int((time.time() - start_time) * 1000)
    return {
        "events": events,
        "count": len(events),
        "latency_ms": latency_ms,
    }


@router.get("/popular")
async def popular(
    user_profile: Annotated[dict, Depends(get_user_profile_required)],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
):
    """Upcoming events ranked by global save count (user_favorites).

    Falls back to soonest upcoming events when no saves exist yet.
    """
    start_time = time.time()
    events = await popular_events(db, limit=limit)
    latency_ms = int((time.time() - start_time) * 1000)
    return {
        "events": events,
        "count": len(events),
        "latency_ms": latency_ms,
    }
