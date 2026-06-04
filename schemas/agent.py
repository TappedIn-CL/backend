from typing import Optional

from pydantic import BaseModel


class UIFilters(BaseModel):
    """Explicit filter selections from the FilterModal UI.

    These are deterministic user constraints (not LLM-inferred), so the agent
    treats them as authoritative and merges them over whatever parse_intent
    extracts from the free-text query. `category` arrives as a taxonomy label
    ("Arts", "Music", ...); price fields are omitted by the frontend unless the
    user actually narrowed that side of the slider.
    """

    category: str | None = None
    price_min: float | None = None
    price_max: float | None = None
    show_free_only: bool = False
    date_from: str | None = None  # "YYYY-MM-DD"
    date_to: str | None = None    # "YYYY-MM-DD", inclusive of the whole day


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
    ui_filters: UIFilters | None = None
