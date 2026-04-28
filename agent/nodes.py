import json
import logging
import os
from openai import OpenAI
from dotenv import load_dotenv

from agent.state import AgentState, EventSchema
from agent.embedding import embed_query
from agent.pinecone_client import fetch_vectors, search_events
from agent.scoring import score_events

load_dotenv()

logger = logging.getLogger(__name__)

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
        semantic_query = query
        query_vector = embed_query(query)
        structured_filters = {"price_max": None, "max_distance": None, "age_restrictions": None, "categories": [], "vibes": [], "tags": []}

    return {
        **state,
        "semantic_query": semantic_query,
        "query_vector": query_vector,
        "filters": structured_filters,
    }


def retrieve_events(state: AgentState) -> AgentState:
    """
    Node 2: Embeds the semantic query and retrieves candidate events from Pinecone.
    candidate_events are populated from Pinecone metadata. Full Supabase hydration
    (description, address, image_url) is added by Allen's hydration step.
    """
    query_text = state["semantic_query"] or state["query"]
    vector = embed_query(query_text)
    matches = search_events(vector, state["filters"], top_k=20)

    candidate_events: list[EventSchema] = [
        {
            "id": m["id"],
            "title": m["metadata"].get("title", ""),
            "venue_name": m["metadata"].get("venue_name", ""),
            "city": m["metadata"].get("city", ""),
            "category": m["metadata"].get("category", ""),
            "tags": m["metadata"].get("tags", []),
            "price_min": m["metadata"].get("price_min", 0.0),
            "price_max": m["metadata"].get("price_max", 0.0),
            "latitude": m["metadata"].get("latitude", 0.0),
            "longitude": m["metadata"].get("longitude", 0.0),
            "description": "",
            "vibe_tags": [],
            "address": "",
            "start_time": "",
            "end_time": None,
            "image_url": None,
            "source_url": "",
        }
        for m in matches
    ]

    return {
        **state,
        "query_vector": vector,
        "candidate_events": candidate_events,
    }


def score_and_rank(state: AgentState) -> AgentState:
    """
    Node 3: Scores and ranks candidate events using cosine similarity blend.
    Uses taste_vector from state if available (set by compute_taste node).
    """
    candidates = state["candidate_events"]
    if not candidates:
        return {
            **state,
            "ranked_events": [],
            "response": f"No events found for '{state['query']}'.",
        }

    query_vector = state["query_vector"] or [0.0] * 1536
    if not state["query_vector"]:
        logger.warning("score_and_rank called with no query_vector; scoring will be arbitrary")
    taste_vector = state.get("taste_vector")
    event_ids = [e["id"] for e in candidates]
    try:
        event_vectors = fetch_vectors(event_ids)
        ranked = score_events(query_vector, taste_vector, candidates, event_vectors)
    except Exception as e:
        logger.error("Scoring failed, returning unranked candidates: %s", e)
        return {
            **state,
            "ranked_events": list(candidates),
            "response": f"Found {len(candidates)} events for '{state['query']}' (ranking unavailable).",
        }

    if ranked:
        response = (
            f"Found {len(ranked)} events matching '{state['query']}'. "
            f"Top pick: {ranked[0]['title']} at {ranked[0]['venue_name']}."
        )
    else:
        response = f"No scoreable events found for '{state['query']}'."

    return {**state, "ranked_events": ranked, "response": response}
