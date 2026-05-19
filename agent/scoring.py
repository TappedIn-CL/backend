from agent.embedding import embed_text
from agent.state import AgentState, EventSchema
import asyncio

QUERY_WEIGHT = 0.7
TASTE_WEIGHT = 0.3


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _build_taste_text(interests: list[str], favorited_tags: list[str]) -> str:
    parts = []
    if interests:
        parts.append("Interests: " + ", ".join(interests))
    if favorited_tags:
        parts.append("Tags: " + ", ".join(favorited_tags))
    return ". ".join(parts)


def compute_taste_vector(
    interests: list[str], favorited_tags: list[str]
) -> list[float] | None:
    """Embed user interests and favorited tags into a taste vector. Returns None on cold-start."""
    if not interests and not favorited_tags:
        return None
    return embed_text(_build_taste_text(interests, favorited_tags))


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
    """Node: compute taste_vector from user_profile and write it to state. Sets taste_vector=None on cold-start."""
    user_profile = state.get("user_profile") or {}
    interests = user_profile.get("interests") or []
    favorited_tags = user_profile.get("favorited_tags") or []
    taste_vector = await asyncio.to_thread(compute_taste_vector, interests, favorited_tags)
    return {**state, "taste_vector": taste_vector}
