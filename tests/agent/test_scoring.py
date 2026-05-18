import math
from unittest.mock import patch
import pytest
from agent.scoring import (
    cosine_similarity,
    compute_taste_vector,
    score_events,
    compute_taste,
    QUERY_WEIGHT,
    TASTE_WEIGHT,
)
from agent.state import AgentState, EventSchema


# ── cosine_similarity ──────────────────────────────────────────────────────

def test_cosine_identical_vectors():
    assert cosine_similarity([1.0, 0.0, 0.0], [1.0, 0.0, 0.0]) == pytest.approx(1.0)


def test_cosine_orthogonal_vectors():
    assert cosine_similarity([1.0, 0.0, 0.0], [0.0, 1.0, 0.0]) == pytest.approx(0.0)


def test_cosine_opposite_vectors():
    assert cosine_similarity([1.0, 0.0, 0.0], [-1.0, 0.0, 0.0]) == pytest.approx(-1.0)


def test_cosine_zero_vector_returns_zero():
    assert cosine_similarity([0.0, 0.0, 0.0], [1.0, 0.0, 0.0]) == 0.0


def test_cosine_partial_overlap():
    # [1,1,0] vs [1,0,0]: dot=1, |a|=sqrt(2), |b|=1 → 1/sqrt(2)
    assert cosine_similarity([1.0, 1.0, 0.0], [1.0, 0.0, 0.0]) == pytest.approx(
        1.0 / math.sqrt(2)
    )


# ── compute_taste_vector ───────────────────────────────────────────────────

def test_compute_taste_vector_empty_returns_none():
    assert compute_taste_vector([], []) is None


def test_compute_taste_vector_interests_only():
    with patch("agent.scoring.embed_text", return_value=[0.1] * 1536) as mock_embed:
        result = compute_taste_vector(["jazz", "outdoor events"], [])
    mock_embed.assert_called_once_with("Interests: jazz, outdoor events")
    assert result == [0.1] * 1536


def test_compute_taste_vector_tags_only():
    with patch("agent.scoring.embed_text", return_value=[0.2] * 1536) as mock_embed:
        result = compute_taste_vector([], ["chill", "outdoor"])
    mock_embed.assert_called_once_with("Tags: chill, outdoor")
    assert result == [0.2] * 1536


def test_compute_taste_vector_combines_interests_and_tags():
    with patch("agent.scoring.embed_text", return_value=[0.3] * 1536) as mock_embed:
        compute_taste_vector(["jazz"], ["chill"])
    mock_embed.assert_called_once_with("Interests: jazz. Tags: chill")


# ── score_events ───────────────────────────────────────────────────────────

_QUERY_VEC = [1.0, 0.0, 0.0]
_TASTE_VEC = [0.0, 1.0, 0.0]


def _make_event(event_id: str, title: str) -> EventSchema:
    return {
        "id": event_id,
        "title": title,
        "description": "",
        "category": "Music",
        "tags": [],
        "vibe_tags": [],
        "venue_name": "Venue",
        "address": "",
        "city": "LA",
        "latitude": 0.0,
        "longitude": 0.0,
        "price_min": 0.0,
        "price_max": 0.0,
        "start_time": "2026-05-10T19:00:00Z",
        "end_time": None,
        "image_url": None,
        "source_url": "",
    }


_EVT_A = _make_event("evt-a", "Query Match")   # vector aligned with _QUERY_VEC
_EVT_B = _make_event("evt-b", "Taste Match")   # vector aligned with _TASTE_VEC

_EVENT_VECTORS = {
    "evt-a": [1.0, 0.0, 0.0],
    "evt-b": [0.0, 1.0, 0.0],
}


def test_score_events_query_weight_dominates_taste():
    # evt-a: 0.7*1.0 + 0.3*0.0 = 0.70
    # evt-b: 0.7*0.0 + 0.3*1.0 = 0.30
    ranked = score_events(_QUERY_VEC, _TASTE_VEC, [_EVT_A, _EVT_B], _EVENT_VECTORS)
    assert ranked[0]["id"] == "evt-a"
    assert ranked[1]["id"] == "evt-b"


def test_score_events_taste_can_win_when_query_is_weak():
    # diagonal query scores both events equally; taste breaks the tie toward evt-b
    diagonal_query = [0.707, 0.707, 0.0]
    # evt-a: 0.7*0.707 + 0.3*0.0   = 0.495
    # evt-b: 0.7*0.707 + 0.3*1.0   = 0.795
    ranked = score_events(diagonal_query, _TASTE_VEC, [_EVT_A, _EVT_B], _EVENT_VECTORS)
    assert ranked[0]["id"] == "evt-b"


def test_score_events_no_taste_vector_uses_query_only():
    ranked = score_events(_QUERY_VEC, None, [_EVT_A, _EVT_B], _EVENT_VECTORS)
    assert ranked[0]["id"] == "evt-a"
    assert ranked[1]["id"] == "evt-b"


def test_score_events_drops_events_with_no_pinecone_vector():
    partial_vectors = {"evt-a": [1.0, 0.0, 0.0]}  # evt-b missing
    ranked = score_events(_QUERY_VEC, _TASTE_VEC, [_EVT_A, _EVT_B], partial_vectors)
    assert len(ranked) == 1
    assert ranked[0]["id"] == "evt-a"


def test_score_events_empty_candidates_returns_empty():
    ranked = score_events(_QUERY_VEC, _TASTE_VEC, [], {})
    assert ranked == []


def test_score_events_all_vectors_missing_returns_empty():
    ranked = score_events(_QUERY_VEC, _TASTE_VEC, [_EVT_A, _EVT_B], {})
    assert ranked == []


# ── compute_taste node ─────────────────────────────────────────────────────

_BASE_STATE: AgentState = {
    "query": "test query",
    "semantic_query": "test query",
    "filters": {},
    "query_vector": [0.1] * 1536,
    "candidate_events": [],
    "ranked_events": [],
    "response": None,
    "user_profile": None,
    "taste_vector": None,
}


@pytest.mark.anyio
async def test_compute_taste_node_no_user_profile_sets_none():
    result = await compute_taste({**_BASE_STATE, "user_profile": None})
    assert result["taste_vector"] is None


@pytest.mark.anyio
async def test_compute_taste_node_empty_profile_sets_none():
    result = await compute_taste(
        {**_BASE_STATE, "user_profile": {"interests": [], "favorited_tags": []}}
    )
    assert result["taste_vector"] is None


@pytest.mark.anyio
async def test_compute_taste_node_missing_keys_sets_none():
    result = await compute_taste({**_BASE_STATE, "user_profile": {}})
    assert result["taste_vector"] is None


@pytest.mark.anyio
async def test_compute_taste_node_valid_profile_sets_taste_vector():
    with patch("agent.scoring.embed_text", return_value=[0.9] * 1536):
        result = await compute_taste(
            {
                **_BASE_STATE,
                "user_profile": {
                    "interests": ["jazz"],
                    "favorited_tags": ["chill"],
                },
            }
        )
    assert result["taste_vector"] == [0.9] * 1536


@pytest.mark.anyio
async def test_compute_taste_node_preserves_rest_of_state():
    result = await compute_taste({**_BASE_STATE, "user_profile": None})
    assert result["query"] == "test query"
    assert result["query_vector"] == [0.1] * 1536


# ── blend weight constants ─────────────────────────────────────────────────

def test_blend_weight_constants_are_correct():
    assert QUERY_WEIGHT == pytest.approx(0.7)
    assert TASTE_WEIGHT == pytest.approx(0.3)
    assert QUERY_WEIGHT + TASTE_WEIGHT == pytest.approx(1.0)


def test_score_events_weights_are_0_7_query_0_3_taste():
    vectors = {
        "evt-a": [1.0, 0.0, 0.0],   # perfectly aligned with query
        "evt-b": [0.0, 1.0, 0.0],   # perfectly aligned with taste
    }
    evt_a = _make_event("evt-a", "A")
    evt_b = _make_event("evt-b", "B")
    ranked = score_events([1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [evt_a, evt_b], vectors)
    assert ranked[0]["id"] == "evt-a"
    ranked_flipped = score_events([0.0, 1.0, 0.0], [1.0, 0.0, 0.0], [evt_a, evt_b], vectors)
    assert ranked_flipped[0]["id"] == "evt-b"
