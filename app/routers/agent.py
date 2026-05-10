import asyncio
import json

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from schemas.agent import AgentQueryRequest


router = APIRouter()

@router.post("/query")
async def query_agent(body: AgentQueryRequest):

    # TODO: replace asyncio.sleep with actual logic
    async def event_generator():
        # -----------------------------------
        # Phase 1: parsing
        # -----------------------------------
        yield {
            "event": "phase",
            "data": json.dumps({
                "phase": "parsing"
            })
        }

        parsed_query = {
            "text": body.query,
            "chips": body.chips
        }

        # TODO: Implement parsing step
        await asyncio.sleep(0.2)

        # -----------------------------------
        # Phase 2: retrieving
        # -----------------------------------
        yield {
            "event": "phase",
            "data": json.dumps({
                "phase": "retrieving"
            })
        }

        #TODO: Implement retrieving step
        await asyncio.sleep(0.2)

        # -----------------------------------
        # Phase 3: hydrating
        # -----------------------------------
        yield {
            "event": "phase",
            "data": json.dumps({
                "phase": "hydrating"
            })
        }

        #TODO: Implement hydrating step
        await asyncio.sleep(0.2)

        # -----------------------------------
        # Phase 4: scoring
        # -----------------------------------
        yield {
            "event": "phase",
            "data": json.dumps({
                "phase": "scoring"
            })
        }

        #TODO: Implement scoring step
        await asyncio.sleep(0.2)

        # -----------------------------------
        # Final Results
        # -----------------------------------
        yield {
            "event": "results",
            "data": json.dumps({
                "events": [{}], # TODO: replace with actual events
                "count": 10, # TODO: replace with actual count
                "latency_ms": 1240 # TODO: replace with actual latency
            })
        }

    return EventSourceResponse(event_generator())
