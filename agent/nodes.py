from agent.state import AgentState, EventSchema


MOCK_EVENTS: list[EventSchema] = [
    {
        "id": "evt-001",
        "title": "Sunset Jazz at The Rooftop",
        "description": "Live jazz quartet at a converted warehouse rooftop with skyline views.",
        "category": "Music",
        "tags": ["outdoor", "21+"],
        "vibe_tags": ["chill", "intimate"],
        "venue_name": "The Rooftop DTLA",
        "address": "820 E 3rd St, Los Angeles, CA",
        "city": "Los Angeles",
        "latitude": 34.0443,
        "longitude": -118.2356,
        "price_min": 15.0,
        "price_max": 15.0,
        "start_time": "2026-04-25T19:00:00Z",
        "end_time": "2026-04-25T23:00:00Z",
        "image_url": "https://example.com/jazz.jpg",
        "source_url": "https://eventbrite.com/e/jazz-rooftop",
    },
    {
        "id": "evt-002",
        "title": "DTLA Art Walk",
        "description": "Free monthly gallery walk featuring local LA artists across 20+ galleries.",
        "category": "Art & Culture",
        "tags": ["outdoor", "free", "family-friendly"],
        "vibe_tags": ["creative", "social"],
        "venue_name": "Arts District",
        "address": "Arts District, Los Angeles, CA",
        "city": "Los Angeles",
        "latitude": 34.0403,
        "longitude": -118.2348,
        "price_min": 0.0,
        "price_max": 0.0,
        "start_time": "2026-04-26T18:00:00Z",
        "end_time": "2026-04-26T22:00:00Z",
        "image_url": "https://example.com/artwalk.jpg",
        "source_url": "https://downtownartwalk.org",
    },
    {
        "id": "evt-003",
        "title": "Thrift Popup in Sawtelle",
        "description": "Curated vintage popup with 30+ local sellers. Affordable finds and good coffee.",
        "category": "Food & Drink",
        "tags": ["indoor", "pop-up", "free"],
        "vibe_tags": ["chill", "creative"],
        "venue_name": "Sawtelle Studio",
        "address": "2130 Sawtelle Blvd, Los Angeles, CA",
        "city": "Los Angeles",
        "latitude": 34.0422,
        "longitude": -118.4472,
        "price_min": 0.0,
        "price_max": 0.0,
        "start_time": "2026-04-26T11:00:00Z",
        "end_time": "2026-04-26T17:00:00Z",
        "image_url": "https://example.com/thrift.jpg",
        "source_url": "https://instagram.com/sawtelle-popup",
    },
    {
        "id": "evt-004",
        "title": "Comedy Night at Westwood Brewing",
        "description": "Stand-up open mic with UCLA comedy club. Drinks, laughs, low key vibes.",
        "category": "Comedy",
        "tags": ["indoor", "21+"],
        "vibe_tags": ["social", "energetic"],
        "venue_name": "Westwood Brewing Co.",
        "address": "1097 Glendon Ave, Los Angeles, CA",
        "city": "Los Angeles",
        "latitude": 34.0635,
        "longitude": -118.4455,
        "price_min": 10.0,
        "price_max": 10.0,
        "start_time": "2026-04-25T21:00:00Z",
        "end_time": "2026-04-25T23:30:00Z",
        "image_url": "https://example.com/comedy.jpg",
        "source_url": "https://eventbrite.com/e/comedy-night",
    },
]


def parse_intent(state: AgentState) -> AgentState:
    """
    Node 1: Parses the user's raw query into a semantic query string + structured filters.
    Currently a pass-through — Week 6 will add LLM-based intent extraction.
    """
    return {
        **state,
        "semantic_query": state["query"],
        "filters": {"source": "mock"},
    }


def retrieve_events(state: AgentState) -> AgentState:
    """
    Node 2: Embeds the semantic query and retrieves candidate events.
    Currently returns hardcoded mock events — Week 5 will wire up real Pinecone search.
    """
    return {
        **state,
        "query_vector": [0.0] * 1536,
        "candidate_events": MOCK_EVENTS,
    }


def score_and_rank(state: AgentState) -> AgentState:
    """
    Node 3: Scores and ranks candidate events against the user query.
    Currently ranks by price (cheapest first) as a mock heuristic — Week 6 will add real scoring.
    """
    ranked = sorted(state["candidate_events"], key=lambda e: e["price_min"])
    response = (
        f"Found {len(ranked)} events matching '{state['query']}'. "
        f"Top pick: {ranked[0]['title']} at {ranked[0]['venue_name']}."
    )
    return {
        **state,
        "ranked_events": ranked,
        "response": response,
    }
