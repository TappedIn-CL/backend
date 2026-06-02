from typing import Optional

from pydantic import BaseModel


class AgentQueryRequest(BaseModel):
    query: str
    chips: list[str] = []
    user_lat: Optional[float] = None  # user location; None if not shared
    user_lng: Optional[float] = None
    # Explicit toggle from the Happening Now button. When True, retrieve_events
    # over-fetches and hydrate_events drops anything not currently in its run
    # window. The parse_intent node also ORs this with its own LLM-inferred
    # time_intent == "now", so a query like "music right now" sets it even
    # without the toggle.
    happening_now: bool = False
