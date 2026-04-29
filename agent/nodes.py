import json
import os
from openai import OpenAI
from dotenv import load_dotenv

from agent.state import AgentState, EventSchema
from agent.embedding import embed_query

load_dotenv()

# Reuse OpenAI client pattern from embedding.py
_chat_client: OpenAI | None = None

def _get_chat_client() -> OpenAI:
    global _chat_client
    if _chat_client is None:
        _chat_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _chat_client

# Event metadata for prompt context
EVENT_CATEGORIES = ["Music", "Art & Culture", "Food & Drink", "Comedy", "Nightlife", "Wellness", "Networking"]
EVENT_TAGS = ["indoor", "outdoor", "free perks", "pop-up", "limited spots"]
EVENT_VIBES = ["chill", "intimate", "creative", "social", "energetic", "hyped", "educational"]

SYSTEM_PROMPT = """You are an event preference extractor. Given a user query about events, extract structured preferences.

Event metadata available:
- Categories: {categories}
- Tags: {tags}
- Vibes: {vibes}

Extract:
1. semantic_query: A natural language string describing the event type, vibes, and atmosphere. This will be used for embedding search.
2. filters: Structured constraints including:
   - price_max: Maximum price user is willing to pay (null if not mentioned)
   - max_distance: Maximum distance in miles (null if not mentioned, only extract if user explicitly says "within X miles")
   - age_restrictions: Age restriction ("21+", "family-friendly", or null if not mentioned)
   - categories: List of event categories (from available categories)
   - vibes: List of vibe tags (from available vibes)
   - tags: List of physical attributes (from available tags)

Chip phrase mappings:
- "foodie" → category: "Food & Drink"
- "date night" → vibe_tags includes "intimate", keep phrase in semantic_query
- "with friends" → vibe_tags includes "social", keep phrase in semantic_query
- "solo" → vibe_tags includes "chill", keep phrase in semantic_query
- "thrifty" / "cheap" → price_max: 20
- "free" → price_max: 0

Respond with valid JSON structure only, no additional text.
""".format(
    categories=", ".join(EVENT_CATEGORIES),
    tags=", ".join(EVENT_TAGS),
    vibes=", ".join(EVENT_VIBES),
)

USER_PROMPT_TEMPLATE = """Extract preferences from this query: "{query}"

Example:
Query: "chill outdoor jazz under $20 this weekend within 10 miles"
{{
  "semantic_query": "chill outdoor jazz music event",
  "filters": {{"price_max": 20, "max_distance": 10, "age_restrictions": "21+", "categories": ["Music"], "vibes": ["chill"], "tags": ["outdoor"]}}
}}

"""

IntentExtraction = dict[str, str | dict[str, list[str] | float | None]]


def parse_intent(state: AgentState) -> AgentState:
    """
    Node 1: Parses the user's raw query into semantic query strings + structured filters.
    Uses LLM to extract intent from natural language.
    """
    query = state["query"]

    try:
        client = _get_chat_client()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": USER_PROMPT_TEMPLATE.format(query=query)},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
        )

        result: IntentExtraction = json.loads(response.choices[0].message.content)

        # Get the first semantic query string (or fallback to original query)
        semantic_query = result.get("semantic_query", query)
        query_vector = embed_query(semantic_query)
        
        filters = result.get("filters", {})

        structured_filters = {
            "price_max": filters.get("price_max"),
            "max_distance": filters.get("max_distance"),
            "age_restrictions": filters.get("age_restrictions"),
            "categories": filters.get("categories", []),
            "vibes": filters.get("vibes", []),
            "tags": filters.get("tags", [])
        }

    except Exception:
        # Fallback to pass-through on error
        semantic_query = query
        filters = {"price_max": None, "max_distance": None, "age_restrictions": None, "categories": [], "vibes": [], "tags": []}

    return {
        **state,
        "semantic_query": semantic_query,
        "query_vector": query_vector,
        "filters": structured_filters,
    }


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
