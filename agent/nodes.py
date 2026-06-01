import asyncio
import json
import logging
import os
import httpx
from openai import AsyncOpenAI
from dotenv import load_dotenv

from agent.state import AgentState, EventSchema
from agent.embedding import embed_query
from agent.pinecone_client import fetch_vectors, search_events
from agent.scoring import score_events
from agent.taxonomy import CATEGORIES, SPECIAL_TAGS, VIBE_TAGS

load_dotenv()

logger = logging.getLogger(__name__)

# Hydration config — used by hydrate_events node.
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
HYDRATION_TIMEOUT_SECONDS = 5.0
MAX_HYDRATION_BATCH = 100

# Reuse OpenAI client pattern from embedding.py
_chat_client: AsyncOpenAI | None = None

def _get_chat_client() -> AsyncOpenAI:
    global _chat_client
    if _chat_client is None:
        _chat_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _chat_client

# Event metadata for prompt context — imported from agent/taxonomy.py so the
# LLM prompt, the DB validator, and the Pinecone filter contract stay aligned.
# Don't reintroduce inline lists here — they will silently drift from the
# canonical vocab and break category/tag filters against Pinecone.

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

Also extract:
- time_intent: The user's temporal intent — exactly one of "now", "today", "tonight", "this_weekend", "this_week", "upcoming", or null if no time is implied. Use "now" only when the user wants something happening right at this moment.
- confidence: Your confidence from 0.0 to 1.0 that you correctly understood what the user is looking for. Use lower values for vague or ambiguous queries.

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
  "filters": {{"price_max": 20, "max_distance": 10, "age_restrictions": "21+", "categories": ["Music"], "vibes": ["chill"], "tags": ["outdoor"]}},
  "time_intent": "this_weekend",
  "confidence": 0.9
}}

"""

IntentExtraction = dict[str, str | dict[str, list[str] | float | None]]

# Allowed temporal intents — mirrors agent.state.TimeIntent. Anything else from
# the LLM is coerced to None so a hallucinated value never reaches downstream
# time-window logic.
VALID_TIME_INTENTS = {"now", "today", "tonight", "this_weekend", "this_week", "upcoming"}


def _coerce_time_intent(value) -> str | None:
    # isinstance guard first: a non-string (e.g. a list from malformed LLM JSON)
    # would raise TypeError on `value in <set>` and is never a valid intent.
    return value if isinstance(value, str) and value in VALID_TIME_INTENTS else None


def _clamp_confidence(value) -> float | None:
    """Clamp a self-reported confidence into [0, 1]; None when unparseable/absent."""
    if value is None:
        return None
    try:
        c = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, c))


async def parse_intent(state: AgentState) -> AgentState:
    """
    Node 1: Parses the user's raw query into semantic query strings + structured filters.
    Uses LLM to extract intent from natural language.
    """
    query = state["query"]

    try:
        client = _get_chat_client()
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": USER_PROMPT_TEMPLATE.format(query=query)},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
        )

        result: IntentExtraction = json.loads(response.choices[0].message.content)
        semantic_query = result.get("semantic_query", query) or query
        filters = result.get("filters", {}) or {}

        structured_filters = {
            "price_max": filters.get("price_max"),
            "max_distance": filters.get("max_distance"),
            "age_restrictions": filters.get("age_restrictions"),
            "categories": filters.get("categories", []) or [],
            "vibes": filters.get("vibes", []) or [],
            "tags": filters.get("tags", []) or [],
        }

        time_intent = _coerce_time_intent(result.get("time_intent"))
        confidence = _clamp_confidence(result.get("confidence"))

    except Exception as e:
        logger.warning("parse_intent LLM call failed, falling back: %s", e)
        semantic_query = query
        structured_filters = {
            "price_max": None,
            "max_distance": None,
            "age_restrictions": None,
            "categories": [],
            "vibes": [],
            "tags": [],
        }
        time_intent = None
        # 0.0 (not None) so the future clarify node treats a total parse failure
        # as low-confidence and short-circuits to ask the user for clarification.
        confidence = 0.0

    query_vector = await asyncio.to_thread(embed_query, semantic_query)

    return {
        **state,
        "semantic_query": semantic_query,
        "query_vector": query_vector,
        "filters": structured_filters,
        "time_intent": time_intent,
        "happening_now": time_intent == "now",
        "confidence": confidence,
    }


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


async def retrieve_events(state: AgentState) -> AgentState:
    """
    Node 2: Retrieves candidate events from Pinecone using the vector
    already computed by parse_intent. Over-fetches and dedups by title so
    repeated scrapes of the same event don't crowd out unique results.
    """
    vector = state["query_vector"]
    if not vector:
        query_text = state["semantic_query"] or state["query"]
        vector = await asyncio.to_thread(embed_query, query_text)

    pinecone_filter = _to_pinecone_filter(state["filters"] or {})

    # Over-fetch so dedup-by-title still leaves ~20 unique candidates.
    matches = await asyncio.to_thread(search_events, vector, pinecone_filter, 40)

    # Dedup by title alone — Supabase has multiple rows for the same logical
    # event when the scraper re-runs against a new article URL (its source_id
    # is hashed from the URL). Venue strings drift between re-extractions
    # ("Irv's Burgers, ..." vs "La Brea, ..." vs "Multiple Locations: ..."),
    # so title is the most stable dedup key. Keep the highest-ranked match.
    candidate_events: list[EventSchema] = []
    seen: set[str] = set()
    for m in matches:
        title = m["metadata"].get("title", "")
        dedupe_key = title.strip().lower()
        if not dedupe_key or dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        candidate_events.append({
            "id": m["id"],
            "title": title,
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
        })
        if len(candidate_events) >= 20:
            break

    return {
        **state,
        "query_vector": vector,
        "candidate_events": candidate_events,
    }


async def hydrate_events(state: AgentState) -> AgentState:
    """
    Node 3: Fetches full Supabase event rows for the Pinecone candidates and
    merges them into hydrated_events, bridging the gap between sparse vector
    metadata and the rich fields the frontend needs.

    Pinecone stores only the fields needed for filtering and scoring:
    title, venue_name, city, category, tags, price_min/max, latitude,
    longitude, and start_time_unix. Fields like description, vibe_tags,
    address, image_url, source_url, and end_time are not in Pinecone and
    arrive here as empty from retrieve_events.

    This node calls GET /events/by-ids?ids=<comma-separated UUIDs> on the
    backend to get full HydratedEventResponse objects from Supabase, and
    merges them onto each candidate. Pinecone's similarity-ranked order is
    preserved through the merge loop so score_and_rank receives events in
    their original relevance order.
    """
    candidates = state.get("candidate_events") or []
    if not candidates:
        return {**state, "hydrated_events": []}

    if len(candidates) > MAX_HYDRATION_BATCH:
        logger.warning(
            "hydrate_events: %d candidates exceed batch cap %d; truncating",
            len(candidates), MAX_HYDRATION_BATCH,
        )
    ids = [e["id"] for e in candidates][:MAX_HYDRATION_BATCH]

    try:
        async with httpx.AsyncClient(timeout=HYDRATION_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{BACKEND_URL}/events/by-ids",
                params={"ids": ",".join(ids)},
            )
            resp.raise_for_status()
            full_rows = resp.json()

        rows_by_id = {row["id"]: row for row in full_rows}

        hydrated: list[EventSchema] = []
        miss_count = 0
        for candidate in candidates:
            full = rows_by_id.get(candidate["id"])
            if full is None:
                # Event exists in Pinecone but was deleted from Supabase;
                # keep sparse data so the slot isn't silently dropped.
                miss_count += 1
                hydrated.append(candidate)
            else:
                # Supabase overwrites candidate fields as source of truth.
                # Exception: lat/lng come only from Pinecone metadata for the
                # demo (event_to_hydrated returns None for both); prefer
                # candidate values when the full row has None.
                merged = {**candidate, **full}
                merged["latitude"] = full.get("latitude") or candidate.get("latitude", 0.0)
                merged["longitude"] = full.get("longitude") or candidate.get("longitude", 0.0)
                hydrated.append(merged)

        if miss_count:
            logger.warning(
                "hydrate_events: %d/%d events found in Pinecone but missing from Supabase",
                miss_count, len(ids),
            )

    except Exception as e:
        logger.error("Hydration failed, returning sparse candidates: %s", e)
        hydrated = list(candidates)

    return {**state, "hydrated_events": hydrated}


async def score_and_rank(state: AgentState) -> AgentState:
    """
    Node 4: Scores and ranks candidate events using a cosine similarity blend.

    Final score = 0.7 * cosine(query_vector, event_vector)
                + 0.3 * cosine(taste_vector, event_vector)

    Falls back to query-only when taste_vector is None (cold-start /
    unauthenticated user). Reads from hydrated_events when available so the
    ranked output carries full Supabase fields (description, vibe_tags, etc).
    """
    candidates = state.get("hydrated_events") or state.get("candidate_events") or []
    if not candidates:
        return {
            **state,
            "ranked_events": [],
            "enriched_events": [],
            "response": f"No events found for '{state['query']}'.",
        }

    query_vector = state["query_vector"] or [0.0] * 1536
    if not state["query_vector"]:
        logger.warning("score_and_rank called with no query_vector; scoring will be arbitrary")

    taste_vector = state.get("taste_vector")
    event_ids = [e["id"] for e in candidates]
    try:
        event_vectors = await asyncio.to_thread(fetch_vectors, event_ids)
        ranked = score_events(
            query_vector,
            taste_vector,
            candidates,
            event_vectors,
            state.get("user_lat"),
            state.get("user_lng"),
        )
    except Exception as e:
        logger.error("Scoring failed, returning unranked candidates: %s", e)
        return {
            **state,
            "ranked_events": list(candidates),
            "enriched_events": [],
            "response": f"Found {len(candidates)} events for '{state['query']}' (ranking unavailable).",
        }

    if ranked:
        response = (
            f"Found {len(ranked)} events matching '{state['query']}'. "
            f"Top pick: {ranked[0]['title']} at {ranked[0]['venue_name']}."
        )
    else:
        response = f"No scoreable events found for '{state['query']}'."

    # ranked is already list[EnrichedEvent] (each carries score + score_breakdown).
    # ranked_events keeps its existing consumers working (additive score_breakdown
    # key); enriched_events is the typed view downstream owners build on.
    return {**state, "ranked_events": ranked, "enriched_events": ranked, "response": response}
