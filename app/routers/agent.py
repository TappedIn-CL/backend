import json
import time
import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from agent.graph import agent
from auth.deps import get_optional_jwt_payload
from db.dependencies import get_db
from app.models.user import User
from schemas.agent import AgentQueryRequest

router = APIRouter()
logger = logging.getLogger(__name__)


async def get_user_profile(
    payload: Annotated[dict | None, Depends(get_optional_jwt_payload)],
    db: Session = Depends(get_db),
) -> dict | None:
    if not payload:
        return None

    user_id = payload.get("sub")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return None

    return {
        "interests": user.interests or [],
        "favorited_tags": [],
    }


@router.post("/query")
async def agent_query(
    payload: AgentQueryRequest,
    user_profile: Annotated[dict | None, Depends(get_user_profile)],
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
