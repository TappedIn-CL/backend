import asyncio
import json
import time

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

        start_time = time.time()
        print(f"start time: {start_time}")

        yield {
            "event": "phase",
            "data": json.dumps({
                "phase": "parsing"
            })
        }

        # TODO: Implement parsing step
        print(f"query: {body.query}")
        print(f"chips: {body.chips}")
        await asyncio.sleep(5)

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
        await asyncio.sleep(5)

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
        await asyncio.sleep(5)

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
        await asyncio.sleep(5)

        # -----------------------------------
        # Final Results
        # -----------------------------------
        yield {
            "event": "results",
            "data": json.dumps({
                "events": [{}], # TODO: replace with actual events
                "count": 10, # TODO: replace with actual count
                "latency_ms": (time.time() - start_time) * 1000 # TODO: replace with actual latency
            })
        }

    return EventSourceResponse(event_generator())
