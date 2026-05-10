import json
import logging
import os
from openai import OpenAI
from dotenv import load_dotenv

from agent.state import AgentState, EventSchema
from agent.embedding import embed_query
from agent.pinecone_client import search_events, fetch_vectors
from agent.scoring import score_events
from agent.taxonomy import CATEGORIES, VIBE_TAGS, SPECIAL_TAGS
from agent.chip_mapping import merge_chips_into_query, chips_to_categories

load_dotenv()

logger = logging.getLogger(__name__)

# Reuse OpenAI client pattern from embedding.py
_chat_client: OpenAI | None = None

def _get_chat_client() -> OpenAI:
    global _chat_client
    if _chat_client is None:
        _chat_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _chat_client

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
- "sports" → category: "Sports", vibe_tags includes "hyped"/"energetic"
- "adventurous" → vibe_tags includes "adventurous"
- "thrifty" / "cheap" → price_max: 20
- "free" → price_max: 0

Respond with valid JSON structure only, no additional text.
""".format(
    categories=", ".join(CATEGORIES),
    tags=", ".join(SPECIAL_TAGS),
    vibes=", ".join(VIBE_TAGS),
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
    Node 1: Parses the user's raw query + chips into a semantic query string +
    structured filters.

    Vibes are intentionally appended to semantic_query (for embedding search)
    and NOT placed in the Pinecone filter dict. _build_record in
    pinecone_client.py does not store vibe_tags in metadata, so a vibes hard
    filter would silently match zero events.
    """
    query = state["query"]
    chips = state.get("chips", []) or []

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
        llm_semantic_query = result.get("semantic_query", query) or query
        llm_filters = result.get("filters", {}) or {}

        # Vibes go into the embedding text, not the filter dict
        llm_vibes = llm_filters.get("vibes", []) or []
        vibes_phrase = " ".join(llm_vibes)

        # Merge chip-derived categories with LLM-extracted categories (dedup, preserve order)
        llm_categories = llm_filters.get("categories", []) or []
        chip_categories = chips_to_categories(chips)
        merged_categories = list(dict.fromkeys([*llm_categories, *chip_categories]))

        structured_filters = {
            "price_max": llm_filters.get("price_max"),
            "max_distance": llm_filters.get("max_distance"),
            "age_restrictions": llm_filters.get("age_restrictions"),
            "categories": merged_categories,
            "tags": llm_filters.get("tags", []) or [],
            # NOTE: vibes deliberately omitted — Pinecone metadata has no vibe_tags,
            # so filtering on them is a silent no-op. They're folded into the embedding instead.
        }

        # Build the text that actually gets embedded:
        #   LLM's cleaned semantic_query + LLM vibes (as text) + chip semantic_phrases
        base_text = f"{llm_semantic_query} {vibes_phrase}".strip()
        semantic_query = merge_chips_into_query(base_text, chips)

    except Exception as e:
        logger.warning("parse_intent LLM call failed, falling back: %s", e)
        semantic_query = merge_chips_into_query(query, chips)
        structured_filters = {
            "price_max": None,
            "max_distance": None,
            "age_restrictions": None,
            "categories": chips_to_categories(chips),
            "tags": [],
        }

    query_vector = embed_query(semantic_query)

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


def _to_pinecone_filter(raw: dict) -> dict:
    """
    Translate parse_intent's structured filters into Pinecone's MongoDB-style
    filter operators.

    Pinecone metadata fields (from _build_record): start_time_unix, latitude,
    longitude, price_min, price_max, city, category (singular!), tags, title,
    venue_name. Anything else is dropped — max_distance and age_restrictions
    are NOT Pinecone-filterable and would need post-query handling on lat/lng
    or as tag matches respectively.
    """
    f: dict = {}
    if raw.get("price_max") is not None:
        f["price_max"] = {"$lte": raw["price_max"]}
    categories = raw.get("categories") or []
    if categories:
        f["category"] = {"$in": categories}
    tags = raw.get("tags") or []
    if tags:
        f["tags"] = {"$in": tags}
    return f


def retrieve_events(state: AgentState) -> AgentState:
    """
    Node 2: Embeds the semantic query and retrieves candidate events from Pinecone.
    candidate_events are populated from Pinecone metadata. Full Supabase hydration
    (description, address, image_url) is added by Allen's hydration step.
    """
    query_text = state["semantic_query"] or state["query"]
    vector = embed_query(query_text)
    pinecone_filter = _to_pinecone_filter(state["filters"] or {})
    matches = search_events(vector, pinecone_filter, top_k=20)

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
