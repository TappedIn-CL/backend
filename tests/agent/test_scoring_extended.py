"""Tests for the extended compute_taste_vector signature and compute_taste node.

Companion to tests/agent/test_scoring.py — covers the favorites-blend feature
and the new vibes input added on the charlton/recommendation-events branch.
"""
import math
from unittest.mock import patch

import pytest

from agent.scoring import compute_taste, compute_taste_vector
from agent.state import AgentState


# ── compute_taste_vector: new signature ────────────────────────────────────

def test_compute_taste_vector_vibes_only_embeds_vibe_text():
    with patch("agent.scoring.embed_text", return_value=[0.5] * 1536) as mock_embed:
        result = compute_taste_vector([], [], vibes=["chill", "intimate"])
    mock_embed.assert_called_once_with("Vibes: chill, intimate")
    assert result == [0.5] * 1536


def test_compute_taste_vector_vectors_only_returns_mean_no_embed_call():
    v1 = [1.0, 0.0, 0.0]
    v2 = [0.0, 1.0, 0.0]
    with patch("agent.scoring.embed_text") as mock_embed:
        result = compute_taste_vector(
            [], [], favorited_event_vectors=[v1, v2]
        )
    mock_embed.assert_not_called()
    assert result == pytest.approx([0.5, 0.5, 0.0])


def test_compute_taste_vector_blend_weights_and_normalization():
    # text_vec aligned with x-axis, event mean aligned with y-axis.
    # blended_raw = 0.6 * [0,1,0] + 0.4 * [1,0,0] = [0.4, 0.6, 0.0]
    # l2 norm = sqrt(0.16 + 0.36) = sqrt(0.52)
    text_vec = [1.0, 0.0, 0.0]
    event_vec = [0.0, 1.0, 0.0]
    with patch("agent.scoring.embed_text", return_value=text_vec):
        result = compute_taste_vector(
            ["jazz"], [], favorited_event_vectors=[event_vec]
        )
    expected_norm = math.sqrt(0.16 + 0.36)
    assert result[0] == pytest.approx(0.4 / expected_norm)
    assert result[1] == pytest.approx(0.6 / expected_norm)
    assert result[2] == pytest.approx(0.0)
    out_norm = math.sqrt(sum(x * x for x in result))
    assert out_norm == pytest.approx(1.0)


def test_compute_taste_vector_blend_means_multiple_event_vectors():
    text_vec = [1.0, 0.0]
    e1 = [0.0, 1.0]
    e2 = [0.0, 3.0]  # mean -> [0, 2]
    with patch("agent.scoring.embed_text", return_value=text_vec):
        result = compute_taste_vector(
            ["x"], [], favorited_event_vectors=[e1, e2]
        )
    # blended_raw = 0.6 * [0, 2] + 0.4 * [1, 0] = [0.4, 1.2]
    expected_norm = math.sqrt(0.16 + 1.44)
    assert result[0] == pytest.approx(0.4 / expected_norm)
    assert result[1] == pytest.approx(1.2 / expected_norm)


def test_compute_taste_vector_mismatched_event_dims_drops_bad_vectors():
    """If event vectors have inconsistent dims, the bad ones are dropped.
    Remaining vector dim still matches text vec → blend proceeds normally."""
    text_vec = [1.0, 0.0]
    good = [0.0, 1.0]
    bad = [0.0, 1.0, 0.0]  # mismatched dim — must be dropped
    with patch("agent.scoring.embed_text", return_value=text_vec):
        result = compute_taste_vector(
            ["x"], [], favorited_event_vectors=[good, bad]
        )
    # mean of just `good`, blended 0.6/0.4 with text
    expected_norm = math.sqrt(0.16 + 0.36)
    assert result[0] == pytest.approx(0.4 / expected_norm)
    assert result[1] == pytest.approx(0.6 / expected_norm)


def test_compute_taste_vector_text_event_dim_mismatch_falls_back_to_text():
    """Documented behavior: when text and event vec dims disagree, return
    text-only rather than crash."""
    text_vec = [1.0, 0.0, 0.0]
    event_vec = [0.5, 0.5]  # 2-d vs text 3-d
    with patch("agent.scoring.embed_text", return_value=text_vec):
        result = compute_taste_vector(
            ["x"], [], favorited_event_vectors=[event_vec]
        )
    assert result == text_vec


def test_compute_taste_vector_back_compat_two_arg_call():
    """Existing callers pass only (interests, favorited_tags) positionally."""
    with patch("agent.scoring.embed_text", return_value=[0.7] * 1536) as mock_embed:
        result = compute_taste_vector(["jazz"], ["chill"])
    mock_embed.assert_called_once_with("Interests: jazz. Tags: chill")
    assert result == [0.7] * 1536


def test_compute_taste_vector_text_format_unchanged_when_vibes_empty():
    """Regression: existing test_scoring.py asserts the exact embed string;
    don't let an empty `vibes` list inject a stray 'Vibes: ' segment."""
    with patch("agent.scoring.embed_text", return_value=[0.0] * 4) as mock_embed:
        compute_taste_vector(["jazz"], ["chill"], vibes=[])
    mock_embed.assert_called_once_with("Interests: jazz. Tags: chill")


def test_compute_taste_vector_all_empty_returns_none():
    with patch("agent.scoring.embed_text") as mock_embed:
        assert compute_taste_vector([], [], vibes=[], favorited_event_vectors=[]) is None
    mock_embed.assert_not_called()


# ── compute_taste node: new behavior with favorited_event_ids ──────────────

_BASE_STATE: AgentState = {
    "query": "q",
    "semantic_query": "q",
    "filters": {},
    "query_vector": [0.1] * 1536,
    "candidate_events": [],
    "hydrated_events": [],
    "ranked_events": [],
    "response": None,
    "user_profile": None,
    "taste_vector": None,
    "chips": [],
}


@pytest.mark.anyio
async def test_compute_taste_node_fetches_favorited_event_vectors():
    """favorited_event_ids in profile → fetch_vectors invoked and blended in."""
    fetched = {"e1": [0.0, 1.0, 0.0], "e2": [0.0, 1.0, 0.0]}
    captured = {}

    def fake_fetch(ids):
        captured["ids"] = list(ids)
        return fetched

    with patch("agent.scoring.fetch_vectors", side_effect=fake_fetch), \
         patch("agent.scoring.embed_text", return_value=[1.0, 0.0, 0.0]):
        result = await compute_taste({
            **_BASE_STATE,
            "user_profile": {
                "interests": ["jazz"],
                "favorited_tags": [],
                "favorited_event_ids": ["e1", "e2"],
            },
        })
    assert captured["ids"] == ["e1", "e2"]
    assert result["taste_vector"] is not None
    # Blended output must be unit-norm.
    norm = math.sqrt(sum(x * x for x in result["taste_vector"]))
    assert norm == pytest.approx(1.0)


@pytest.mark.anyio
async def test_compute_taste_node_pinecone_failure_falls_back_to_text():
    """If fetch_vectors raises, taste_vector still computed from text alone."""
    def boom(ids):
        raise RuntimeError("pinecone down")

    with patch("agent.scoring.fetch_vectors", side_effect=boom), \
         patch("agent.scoring.embed_text", return_value=[0.42] * 1536):
        result = await compute_taste({
            **_BASE_STATE,
            "user_profile": {
                "interests": ["jazz"],
                "favorited_tags": [],
                "favorited_event_ids": ["e1"],
            },
        })
    assert result["taste_vector"] == [0.42] * 1536


@pytest.mark.anyio
async def test_compute_taste_node_no_favorited_ids_skips_pinecone_call():
    with patch("agent.scoring.fetch_vectors") as mock_fetch, \
         patch("agent.scoring.embed_text", return_value=[0.1] * 1536):
        await compute_taste({
            **_BASE_STATE,
            "user_profile": {
                "interests": ["jazz"],
                "favorited_tags": [],
            },
        })
    mock_fetch.assert_not_called()


@pytest.mark.anyio
async def test_compute_taste_node_uses_vibes_from_profile():
    with patch("agent.scoring.embed_text", return_value=[0.3] * 1536) as mock_embed:
        await compute_taste({
            **_BASE_STATE,
            "user_profile": {
                "interests": ["jazz"],
                "favorited_tags": [],
                "vibes": ["chill"],
            },
        })
    mock_embed.assert_called_once_with("Interests: jazz. Vibes: chill")
