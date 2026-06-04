import asyncio
import logging
import math

from agent.embedding import embed_text
from agent.state import AgentState, EnrichedEvent, EventSchema
from agent.pinecone_client import fetch_vectors

logger = logging.getLogger(__name__)

QUERY_WEIGHT = 0.7
TASTE_WEIGHT = 0.3

# Distance penalty: a far event is nudged down so a closer one with equal
# semantic relevance ranks first. Provisional/untuned — these only take effect
# once a caller passes user coordinates; with no coords the penalty is always 0
# and ranking is identical to the pure-similarity blend.
DISTANCE_WEIGHT = 0.2            # maximum penalty, applied at/over the reference distance
DISTANCE_REFERENCE_MILES = 25.0  # distance at which the penalty saturates
EARTH_RADIUS_MILES = 3958.8

# Blend favorited-event vectors (behavioral signal) heavier than self-reported
# interests text (declarative signal). Behavior beats stated preference but
# interests give breadth when a user has only one or two favorites.
FAVORITES_WEIGHT = 0.6
INTERESTS_TEXT_WEIGHT = 0.4


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in miles between two lat/lng points."""
    rlat1, rlng1, rlat2, rlng2 = map(math.radians, (lat1, lng1, lat2, lng2))
    dlat = rlat2 - rlat1
    dlng = rlng2 - rlng1
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlng / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(min(1.0, math.sqrt(a)))


def distance_penalty(
    user_lat: float | None,
    user_lng: float | None,
    event_lat: float | None,
    event_lng: float | None,
) -> float:
    """Penalty in [0, DISTANCE_WEIGHT] for how far an event is from the user.

    Returns 0.0 when the user shared no location, or when the event has no
    coordinates. (0.0, 0.0) is the sentinel for missing coords in sparse
    Pinecone metadata, so it is treated as "no coordinates" rather than a real
    point in the Atlantic.
    """
    if user_lat is None or user_lng is None:
        return 0.0
    if not event_lat or not event_lng:
        return 0.0
    miles = haversine_miles(user_lat, user_lng, event_lat, event_lng)
    return DISTANCE_WEIGHT * min(miles / DISTANCE_REFERENCE_MILES, 1.0)


def _l2_normalize(v: list[float]) -> list[float]:
    norm = sum(x * x for x in v) ** 0.5
    if norm == 0.0:
        return v
    return [x / norm for x in v]


def _mean_vector(vectors: list[list[float]]) -> list[float] | None:
    if not vectors:
        return None
    dim = len(vectors[0])
    # All vectors are 1536-dim OpenAI embeddings; bail loudly if a malformed
    # vector slips through so we don't silently average mismatched widths.
    if any(len(v) != dim for v in vectors):
        logger.warning("mean_vector: dropping vectors with mismatched dim")
        vectors = [v for v in vectors if len(v) == dim]
        if not vectors:
            return None
    return [sum(v[i] for v in vectors) / len(vectors) for i in range(dim)]


def _clean_str_list(items: list[str] | None) -> list[str]:
    if not items:
        return []
    return [str(x).strip() for x in items if x is not None and str(x).strip()]


def _build_taste_text(
    interests: list[str],
    vibes: list[str],
    favorited_tags: list[str],
) -> str:
    interests = _clean_str_list(interests)
    vibes = _clean_str_list(vibes)
    favorited_tags = _clean_str_list(favorited_tags)
    parts = []
    if interests:
        parts.append("Interests: " + ", ".join(interests))
    if vibes:
        parts.append("Vibes: " + ", ".join(vibes))
    if favorited_tags:
        parts.append("Tags: " + ", ".join(favorited_tags))
    return ". ".join(parts)


def compute_taste_vector(
    interests: list[str],
    favorited_tags: list[str],
    vibes: list[str] | None = None,
    favorited_event_vectors: list[list[float]] | None = None,
) -> list[float] | None:
    """Build a taste vector from text signals (interests/vibes/tags) and
    behavioral signals (favorited event vectors). Returns None on cold-start.

    Blend:
      both present     → l2_normalize(0.6 * mean(event_vecs) + 0.4 * text_vec)
      text only        → text_vec
      vectors only     → mean(event_vecs)
      neither          → None
    """
    vibes = _clean_str_list(vibes)
    interests = _clean_str_list(interests)
    favorited_tags = _clean_str_list(favorited_tags)
    favorited_event_vectors = favorited_event_vectors or []

    text_present = bool(interests or vibes or favorited_tags)
    text_vec = (
        embed_text(_build_taste_text(interests, vibes, favorited_tags))
        if text_present
        else None
    )

    event_vec = _mean_vector(favorited_event_vectors)

    if text_vec is not None and event_vec is not None:
        if len(text_vec) != len(event_vec):
            logger.warning(
                "compute_taste_vector: dim mismatch text=%d event=%d; using text only",
                len(text_vec), len(event_vec),
            )
            return text_vec
        blended = [
            FAVORITES_WEIGHT * e + INTERESTS_TEXT_WEIGHT * t
            for e, t in zip(event_vec, text_vec)
        ]
        return _l2_normalize(blended)

    return text_vec or event_vec


def score_events(
    query_vector: list[float],
    taste_vector: list[float] | None,
    events: list[EventSchema],
    event_vectors: dict[str, list[float]],
    user_lat: float | None = None,
    user_lng: float | None = None,
) -> list[EnrichedEvent]:
    """Rank events by final_score = blended_similarity - distance_penalty, where
    blended = 0.7*cosine(query, event) + 0.3*cosine(taste, event) (query-only
    when taste_vector is None). Events missing from event_vectors are dropped.

    Each returned event carries:
      - "score": the final_score it was ranked on
      - "score_breakdown": {query_sim, taste_sim, distance_penalty, final_score}

    Backward-compat: with no user location, distance_penalty is 0.0 for every
    event, so final_score == blended and ranking is identical to before.
    """
    scored: list[tuple[float, EnrichedEvent]] = []
    for event in events:
        ev = event_vectors.get(event["id"])
        if ev is None:
            continue
        query_sim = cosine_similarity(query_vector, ev)
        if taste_vector is not None:
            taste_sim = cosine_similarity(taste_vector, ev)
            blended = QUERY_WEIGHT * query_sim + TASTE_WEIGHT * taste_sim
        else:
            taste_sim = 0.0
            blended = query_sim
        penalty = distance_penalty(
            user_lat, user_lng, event.get("latitude"), event.get("longitude")
        )
        final_score = blended - penalty
        breakdown = {
            "query_sim": query_sim,
            "taste_sim": taste_sim,
            "distance_penalty": penalty,
            "final_score": final_score,
        }
        scored.append((final_score, {**event, "score": final_score, "score_breakdown": breakdown}))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [enriched for _, enriched in scored]


async def compute_taste(state: AgentState) -> AgentState:
    """Node: compute taste_vector from user_profile and write it to state.

    user_profile may include:
      - interests, vibes, favorited_tags: text signals embedded together
      - favorited_event_ids: vectors fetched from Pinecone, mean-blended in

    Sets taste_vector=None on cold-start (no signals at all).
    """
    user_profile = state.get("user_profile") or {}
    interests = user_profile.get("interests") or []
    favorited_tags = user_profile.get("favorited_tags") or []
    vibes = user_profile.get("vibes") or []
    favorited_event_ids = user_profile.get("favorited_event_ids") or []

    favorited_event_vectors: list[list[float]] = []
    if favorited_event_ids:
        try:
            vectors_by_id = await asyncio.to_thread(
                fetch_vectors, favorited_event_ids
            )
            favorited_event_vectors = list(vectors_by_id.values())
        except Exception as e:
            logger.warning(
                "compute_taste: failed to fetch favorited event vectors: %s", e
            )

    taste_vector = await asyncio.to_thread(
        compute_taste_vector,
        interests,
        favorited_tags,
        vibes,
        favorited_event_vectors,
    )
    return {**state, "taste_vector": taste_vector}
