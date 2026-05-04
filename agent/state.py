from typing import TypedDict, Optional, Any


class EventSchema(TypedDict):
    id: str
    title: str
    description: str
    category: str
    tags: list[str]
    vibe_tags: list[str]
    venue_name: str
    address: str
    city: str
    latitude: float
    longitude: float
    price_min: float
    price_max: float
    start_time: str
    end_time: Optional[str]
    image_url: Optional[str]
    source_url: str


class AgentState(TypedDict):
    query: str                          # raw user input
    semantic_query: str                 # cleaned text for embedding
    filters: dict[str, Any]            # extracted structured filters (price, date, distance)
    query_vector: Optional[list[float]] # embedded semantic_query
    candidate_events: list[EventSchema] # top-K results from Pinecone
    ranked_events: list[EventSchema]    # final scored + ranked events
    response: Optional[str]            # plain-English response to user
    user_profile: Optional[dict]        # {"interests": [...], "favorited_tags": [...]}
    taste_vector: Optional[list[float]] # computed by compute_taste node
