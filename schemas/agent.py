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
    ui_filters: UIFilters | None = None
