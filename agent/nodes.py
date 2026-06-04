import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from openai import AsyncOpenAI
from dotenv import load_dotenv

from agent.state import AgentState, EventSchema
from agent.embedding import embed_query
from agent.chip_mapping import merge_chips_into_query, chips_to_categories
from agent.pinecone_client import fetch_vectors, search_events
from agent.scoring import score_events
from agent.taxonomy import CATEGORIES, SPECIAL_TAGS, VIBE_TAGS

load_dotenv()

logger = logging.getLogger(__name__)

# Hydration config — used by hydrate_events node.
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
HYDRATION_TIMEOUT_SECONDS = 5.0
MAX_HYDRATION_BATCH = 100

# Time filter config — matches scrapers/run_cleanup.GRACE_HOURS and
# app/utils/event_utils.DEFAULT_EVENT_DURATION_HOURS so an event's "is over"
# determination is identical at scrape time, cleanup time, and query time.
DEFAULT_EVENT_DURATION_HOURS = 3
LOCAL_TZ = ZoneInfo("America/Los_Angeles")

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

    # Fold the frontend's selected chips into both the embedding signal and the
    # category filter. Chip vibe_tags intentionally land in the embedding (via
    # each chip's semantic_phrase) rather than a Pinecone filter — vibe_tags are
    # not stored in Pinecone metadata, so a $in on them would match zero events.
    # Chip categories ARE filterable, so union them onto whatever the LLM
    # inferred. Done outside the try/except so chips still apply if the LLM call
    # failed. Unmapped chips (e.g. "Happening Now") are ignored by the helpers.
    chips = state.get("chips") or []
    semantic_query = merge_chips_into_query(semantic_query, chips)
    chip_categories = chips_to_categories(chips)
    if chip_categories:
        existing_cats = structured_filters.get("categories") or []
        structured_filters["categories"] = list(
            dict.fromkeys([*existing_cats, *chip_categories])
        )

    query_vector = await asyncio.to_thread(embed_query, semantic_query)

    return {
        **state,
        "semantic_query": semantic_query,
        "query_vector": query_vector,
        "filters": structured_filters,
        "time_intent": time_intent,
        # Explicit toggle from the Happening Now button wins. The LLM-inferred
        # time_intent == "now" can still flip it ON for queries like "music
        # right now" without the toggle, but never OFF if the user toggled it.
        "happening_now": bool(state.get("happening_now")) or (time_intent == "now"),
        "confidence": confidence,
    }


def _merge_ui_filters(filters: dict, ui: dict | None) -> dict:
    """
    Fold explicit FilterModal selections into the LLM-parsed filters.

    UI selections are deterministic user constraints, so they win over whatever
    parse_intent inferred from the free-text query. Category labels arrive
    already aligned to taxonomy.CATEGORIES (FilterModal sends "Arts", "Music",
    ...), so they map straight onto the Pinecone `category` $in clause. Price
    fields are only present when the user narrowed that side of the slider
    (the frontend omits untouched bounds), so a plain merge is correct.
    """
    if not ui:
        return filters
    merged = dict(filters)
    category = ui.get("category")
    if category and category != "All":
        merged["categories"] = [category]
    if ui.get("price_min") is not None:
        merged["price_min"] = ui["price_min"]
    if ui.get("price_max") is not None:
        merged["price_max"] = ui["price_max"]
    if ui.get("show_free_only"):
        merged["show_free_only"] = True
    if ui.get("date_from"):
        merged["date_from"] = ui["date_from"]
    if ui.get("date_to"):
        merged["date_to"] = ui["date_to"]
    return merged


def _iso_date_to_unix(iso: str, *, end_of_day: bool = False) -> int | None:
    """Convert a "YYYY-MM-DD" UI date to a unix timestamp.

    `date_to` is inclusive of the whole selected day, so end_of_day pushes it to
    23:59:59 of that date. Returns None on a malformed string so a bad value
    drops the bound instead of raising.
    """
    try:
        dt = datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return None
    if end_of_day:
        dt = dt + timedelta(days=1) - timedelta(seconds=1)
    return int(dt.timestamp())


def _price_filter(raw: dict) -> dict:
    """
    Translate price intent into Pinecone metadata clauses using OVERLAP
    semantics: an event matches the budget band [price_min, price_max] when its
    own [price_min, price_max] range intersects it.

    The field-flip is intentional and IS the intersection test — do not
    "correct" it to same-name clauses:
      - the filter's MAX constrains the event's MIN (cheapest tier <= ceiling)
      - the filter's MIN constrains the event's MAX (top tier >= floor)
    Each side is only emitted when the user narrowed it, so an untouched slider
    adds no price constraint at all.

    "Free" is special-cased to price_max == 0 (matching formatPriceRange and the
    show_free_only toggle) so a $0 budget ceiling — whether from the free toggle,
    the slider dragged to 0, or the LLM emitting price_max=0 for "free" — means
    truly free, not the looser "has a free tier" the overlap rule would give.
    """
    price_max = raw.get("price_max")
    if raw.get("show_free_only") or price_max == 0:
        return {"price_max": {"$eq": 0}}
    f: dict = {}
    if price_max is not None:                      # filter upper bound was narrowed
        f["price_min"] = {"$lte": price_max}       # event's cheapest tier <= budget ceiling
    if raw.get("price_min") is not None:           # filter lower bound was narrowed
        f["price_max"] = {"$gte": raw["price_min"]}  # event's top tier >= budget floor
    return f


def _to_pinecone_filter(raw: dict) -> dict:
    """
    Translate structured filters (LLM-parsed + merged UI) into Pinecone's
    MongoDB-style filter operators.

    Pinecone metadata fields (from _build_record): start_time_unix, latitude,
    longitude, price_min, price_max, city, category (singular!), tags, title,
    venue_name. Anything else is dropped — max_distance and age_restrictions
    are NOT Pinecone-filterable and would need post-query handling on lat/lng
    or as tag matches respectively. Pinecone implicitly ANDs the top-level keys.
    """
    f: dict = {}
    f.update(_price_filter(raw))
    categories = raw.get("categories") or []
    if categories:
        f["category"] = {"$in": categories}
    tags = raw.get("tags") or []
    if tags:
        f["tags"] = {"$in": tags}
    # Date range → start_time_unix bounds. upcoming_only_filter merges these
    # with its "not yet started" floor (keeping the later $gte), so a past
    # date_from can't surface events that already happened.
    date_from = raw.get("date_from")
    date_to = raw.get("date_to")
    if date_from or date_to:
        rng: dict = {}
        if date_from:
            lo = _iso_date_to_unix(date_from)
            if lo is not None:
                rng["$gte"] = lo
        if date_to:
            hi = _iso_date_to_unix(date_to, end_of_day=True)
            if hi is not None:
                rng["$lte"] = hi
        if rng:
            f["start_time_unix"] = rng
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

    merged_filters = _merge_ui_filters(state["filters"] or {}, state.get("ui_filters"))
    pinecone_filter = _to_pinecone_filter(merged_filters)

    happening_now = bool(state.get("happening_now"))
    time_mode = "happening_now" if happening_now else "upcoming"
    # In happening_now mode the candidate pool is much smaller (only events
    # currently in progress), and the lenient 24h window can return some that
    # have already ended — which hydrate_events drops via effective_end_time.
    # Over-fetch more so the post-filter dedup still leaves ~20 candidates.
    top_k = 60 if happening_now else 40
    matches = await asyncio.to_thread(
        search_events, vector, pinecone_filter, top_k, time_mode
    )

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


def _passes_time_filter(event: EventSchema, now_la: datetime, happening_now: bool) -> bool:
    """Drop events that have already ended; when happening_now is True, also drop
    events that haven't started yet.

    Uses the hydrated event's `end_time` when present (populated by Allen's
    effective_end_time helper in event_to_hydrated). Falls back to
    start + DEFAULT_EVENT_DURATION_HOURS when end_time is None/empty so this
    works against legacy rows whose end_time column is still NULL.

    Datetimes are compared as naive LA-local, matching Supabase's storage
    convention. Bad/missing start_time → drop (can't reason about timing).
    """
    start_str = event.get("start_time")
    if not start_str:
        return False
    try:
        start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
        if start.tzinfo is not None:
            start = start.astimezone(LOCAL_TZ).replace(tzinfo=None)
    except (ValueError, TypeError):
        return False

    end_str = event.get("end_time")
    end: datetime | None = None
    if end_str:
        try:
            end = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
            if end.tzinfo is not None:
                end = end.astimezone(LOCAL_TZ).replace(tzinfo=None)
        except (ValueError, TypeError):
            end = None
    if end is None:
        end = start + timedelta(hours=DEFAULT_EVENT_DURATION_HOURS)

    if happening_now:
        return start <= now_la <= end
    # Default: just hide events that are over.
    return end >= now_la


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
        # Sparse Pinecone candidates have no start_time / description / address,
        # so returning them to the UI produces broken-looking cards. Better to
        # surface "no events found" honestly than to render empty placeholders.
        logger.error("Hydration failed, returning empty: %s", e)
        hydrated = []

    # Always drop events that have already ended; when the Happening Now toggle
    # is on, ALSO drop events that haven't started yet. This runs unconditionally
    # because past events polluting default search results was the user-facing
    # bug — Happening Now is a stricter version of the same filter.
    now_la = datetime.now(LOCAL_TZ).replace(tzinfo=None)
    happening_now = bool(state.get("happening_now"))
    before = len(hydrated)
    hydrated = [e for e in hydrated if _passes_time_filter(e, now_la, happening_now)]
    dropped = before - len(hydrated)
    if dropped:
        logger.info(
            "hydrate_events: time filter dropped %d/%d events (happening_now=%s)",
            dropped, before, happening_now,
        )

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
    # Trust hydrated_events as the source of truth — never fall back to raw
    # candidate_events. Those are sparse Pinecone metadata (no description /
    # start_time / address), so rendering them produces broken cards AND
    # bypasses the hydrate-layer time filter that drops past events.
    candidates = state.get("hydrated_events") or []
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
