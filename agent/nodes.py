import asyncio
import json
import logging
import os
import httpx
from openai import OpenAI
from dotenv import load_dotenv

from agent.state import AgentState, EventSchema
from agent.embedding import embed_query
from agent.pinecone_client import fetch_vectors, search_events
from agent.scoring import score_events

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

    query_vector = await asyncio.to_thread(embed_query, semantic_query)
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
    already computed by parse_intent.
    """
    vector = state["query_vector"]
    if not vector:
        query_text = state["semantic_query"] or state["query"]
        vector = await asyncio.to_thread(embed_query, query_text)

    pinecone_filter = _to_pinecone_filter(state["filters"] or {})
    matches = await asyncio.to_thread(search_events, vector, pinecone_filter, top_k=20)

    candidate_events: list[EventSchema] = [
        {
    # Over-fetch so dedup-by-(title, venue) still leaves ~20 unique candidates.
    matches = search_events(vector, pinecone_filter, top_k=40)

    # Dedup by title alone — Supabase has multiple rows for the same logical
    # event when the scraper re-runs against a new article URL (its source_id
    # is hashed from the URL). Venue strings drift between re-extractions
    # ("Irv's Burgers, ..." vs "La Brea, ..." vs "Multiple Locations: ..."),
    # so title is the most stable dedup key. Keep the highest-ranked match.
    candidate_events: list[EventSchema] = []
    seen: set[str] = set()
    for m in matches:
        title = m["metadata"].get("title", "")
        venue = m["metadata"].get("venue_name", "")
        dedupe_key = title.strip().lower()
        if not dedupe_key or dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        candidate_events.append({
            "id": m["id"],
            "title": title,
            "venue_name": venue,
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
    Node 3: Fetch full event rows directly from the database.
    This populates description, address, image_url, and vibe_tags which are
    not stored in Pinecone metadata.
    """
def hydrate_events(state: AgentState) -> AgentState:
    """
    Node 3: Fetches full Supabase event rows for the Pinecone candidates and
    merges them into hydrated_events, bridging the gap between sparse vector
    metadata and the rich fields the frontend needs.

    Pinecone stores only the fields needed for filtering and scoring:
    title, venue_name, city, category, tags, price_min/max, latitude,
    longitude, and start_time_unix. Fields like description, vibe_tags,
    address, image_url, source_url, and end_time are not in Pinecone and
    arrive here as empty from retrieve_events.

    This node calls GET /events/by-ids?ids=<comma-separated UUIDs> to get
    full HydratedEventResponse objects from Supabase, and merges them onto
    each candidate.

    Pinecone's similarity-ranked order from retrieve_events is preserved
    through the merge loop so score_and_rank receives events in their
    original relevance order.
    """
    # --- Guard: nothing to hydrate ---
    candidates = state.get("candidate_events") or []
    if not candidates:
        return {**state, "hydrated_events": []}

    ids = [e["id"] for e in candidates][:MAX_HYDRATION_BATCH]

    try:
        from db.session import SessionLocal
        from app.models.event import Event
        from app.utils.event_utils import event_to_hydrated
        import uuid as uuid_mod

        def _fetch_from_db():
            db = SessionLocal()
            try:
                parsed_ids = [uuid_mod.UUID(i) for i in ids]
                events = db.query(Event).filter(Event.id.in_(parsed_ids)).all()
                by_id = {str(e.id): e for e in events}
                return {
                    eid: {
                        "id": str(e.id),
                        "title": e.title,
                        "description": e.description or "",
                        "category": e.category or "",
                        "tags": [t.strip() for t in (e.special_tags or "").split(",") if t.strip()],
                        "vibe_tags": [t.strip() for t in (e.vibe_tags or "").split(",") if t.strip()],
                        "venue_name": e.location or "",
                        "address": e.location or "",
                        "city": "Los Angeles",
                        "latitude": 0.0,
                        "longitude": 0.0,
                        "price_min": e.cost or 0.0,
                        "price_max": e.cost or 0.0,
                        "start_time": e.date.isoformat() if e.date else "",
                        "end_time": None,
                        "image_url": None,
                        "source_url": "",
                    }
                    for eid, e in by_id.items()
                }
            finally:
                db.close()

        rows_by_id = await asyncio.to_thread(_fetch_from_db)

        hydrated: list[EventSchema] = []
        for candidate in candidates:
            full = rows_by_id.get(candidate["id"])
            if full is None:
                hydrated.append(candidate)
            else:
                hydrated.append({**candidate, **full})

    except Exception as e:
    # --- Build ID list, warn if truncation occurs ---
    if len(candidates) > MAX_HYDRATION_BATCH:
        logger.warning(
            "hydrate_events: %d candidates exceed batch cap %d; truncating",
            len(candidates), MAX_HYDRATION_BATCH,
        )
    ids = [e["id"] for e in candidates][:MAX_HYDRATION_BATCH]

    try:
        # --- Fetch full rows from Supabase via the backend endpoint ---
        resp = httpx.get(
            f"{BACKEND_URL}/events/by-ids",
            params={"ids": ",".join(ids)},
            timeout=HYDRATION_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        full_rows = resp.json()

        # --- Index full rows by id for O(1) lookup during merge ---
        rows_by_id = {row["id"]: row for row in full_rows}

        # --- Merge: walk candidates in Pinecone order, overlay Supabase fields ---
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
        # --- Fallback: pass sparse candidates through so the pipeline survives ---
        logger.error("Hydration failed, returning sparse candidates: %s", e)
        hydrated = list(candidates)

    return {**state, "hydrated_events": hydrated}


async def score_and_rank(state: AgentState) -> AgentState:
    """
    Node 4: Scores and ranks candidate events using cosine similarity blend.
    Uses taste_vector from state if available (set by compute_taste node).
    """
    candidates = state.get("hydrated_events") or state.get("candidate_events") or []
def score_and_rank(state: AgentState) -> AgentState:
    """
    Node 4: Scores and ranks candidate events using a cosine similarity blend.

    Final score = 0.7 * cosine(query_vector, event_vector)
                + 0.3 * cosine(taste_vector, event_vector)

    Falls back to query-only when taste_vector is None (cold-start /
    unauthenticated user). Reads from hydrated_events when available so the
    ranked output carries full Supabase fields (description, vibe_tags, etc).
    """
    candidates = state.get("hydrated_events") or state["candidate_events"]
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
        event_vectors = await asyncio.to_thread(fetch_vectors, event_ids)
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
