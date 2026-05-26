import asyncio
import logging

from agent.embedding import embed_text
from agent.state import AgentState, EventSchema
from agent.pinecone_client import fetch_vectors

logger = logging.getLogger(__name__)

QUERY_WEIGHT = 0.7
TASTE_WEIGHT = 0.3

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
) -> list[EventSchema]:
    """Rank events by 0.7*cosine(query, event) + 0.3*cosine(taste, event). Falls back to query-only when taste_vector is None. Events missing from event_vectors are dropped.

    Returns each event with a "score" field attached (blended cosine score) so
    downstream consumers (UI, agent response) can display ranking confidence.
    """
    scored = []
    for event in events:
        ev = event_vectors.get(event["id"])
        if ev is None:
            continue
        query_score = cosine_similarity(query_vector, ev)
        if taste_vector is not None:
            taste_score = cosine_similarity(taste_vector, ev)
            blended = QUERY_WEIGHT * query_score + TASTE_WEIGHT * taste_score
        else:
            blended = query_score
        scored.append((blended, event))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [{**event, "score": score} for score, event in scored]


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
