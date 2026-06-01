from typing import TypedDict, Optional, Any, Literal


# Temporal intent the user expresses in a query. Allen's intent work refines how
# these are produced/consumed; parse_intent only self-reports one of these (or
# None). Keep this list and parse_intent's VALID_TIME_INTENTS in sync.
TimeIntent = Literal["now", "today", "tonight", "this_weekend", "this_week", "upcoming"]


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


class ScoreBreakdown(TypedDict):
    """Per-event transparency for how its final ranking score was computed."""
    query_sim: float          # cosine(query_vector, event_vector)
    taste_sim: float          # cosine(taste_vector, event_vector); 0.0 when no taste vector
    distance_penalty: float   # subtracted from the blended score; 0.0 when no user location
    final_score: float        # the value events are actually ranked on


class EnrichedEvent(EventSchema):
    """A ranked event plus its scoring transparency. score == score_breakdown.final_score."""
    score: float
    score_breakdown: ScoreBreakdown


class AgentState(TypedDict):
    query: str                          # raw user input
    chips: list[str]                    # selected mood chips from frontend (e.g. ["Chill", "Foodie"])
    semantic_query: str                 # cleaned + chip-enriched text for embedding
    filters: dict[str, Any]            # extracted structured filters (price, date, distance, categories — NO vibes)
    query_vector: Optional[list[float]] # embedded semantic_query
    candidate_events: list[EventSchema] # top-K results from Pinecone (sparse metadata)
    hydrated_events: list[EventSchema]  # candidate_events + full Supabase rows
    ranked_events: list[EventSchema]    # final scored + ranked events
    response: Optional[str]            # plain-English response to user
    user_profile: Optional[dict]        # {"interests": [...], "favorited_tags": [...]}
    taste_vector: Optional[list[float]] # computed by compute_taste node
    user_lat: Optional[float]           # user location latitude, from request (None if not shared)
    user_lng: Optional[float]           # user location longitude, from request
    time_intent: Optional[TimeIntent]   # parsed temporal intent (parse_intent)
    happening_now: bool                 # derived: time_intent == "now"
    confidence: Optional[float]         # parse_intent self-reported 0–1 (feeds future clarify node)
    enriched_events: list[EnrichedEvent]  # final ranked events + score breakdown


def initial_state(
    *,
    query: str,
    chips: list[str],
    user_profile: Optional[dict],
    user_lat: Optional[float],
    user_lng: Optional[float],
) -> AgentState:
    """Build the seed AgentState for a fresh agent run.

    Single source of truth for the initial state so every entrypoint stays in
    sync with AgentState (guarded by test_initial_state_keys_match_agentstate_contract).
    Nodes fill in the remaining fields as the graph executes.
    """
    return {
        "query": query,
        "chips": chips,
        "semantic_query": "",
        "filters": {},
        "query_vector": None,
        "candidate_events": [],
        "hydrated_events": [],
        "ranked_events": [],
        "response": None,
        "user_profile": user_profile,
        "taste_vector": None,
        "user_lat": user_lat,
        "user_lng": user_lng,
        "time_intent": None,
        "happening_now": False,
        "confidence": None,
        "enriched_events": [],
    }
