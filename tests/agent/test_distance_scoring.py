"""Tests for distance-aware scoring and the per-event score_breakdown.

Covers the new haversine helper, the distance_penalty mapping, and the
score_breakdown attached by score_events — including the backward-compat
guarantee that, with no user location, final_score equals the old blended
score and ranking is unchanged.
"""

import pytest

from agent.scoring import (
    haversine_miles,
    distance_penalty,
    score_events,
    DISTANCE_WEIGHT,
    QUERY_WEIGHT,
    TASTE_WEIGHT,
)
from agent.state import EventSchema


# ── haversine_miles ─────────────────────────────────────────────────────────

def test_haversine_zero_distance():
    assert haversine_miles(34.05, -118.24, 34.05, -118.24) == pytest.approx(0.0, abs=1e-6)


def test_haversine_symmetry():
    a = haversine_miles(34.05, -118.24, 33.94, -118.40)
    b = haversine_miles(33.94, -118.40, 34.05, -118.24)
    assert a == pytest.approx(b)


def test_haversine_known_distance_dtla_to_lax():
    # Downtown LA (34.0522, -118.2437) to LAX (33.9416, -118.4085):
    # great-circle distance is ~12.1 miles.
    miles = haversine_miles(34.0522, -118.2437, 33.9416, -118.4085)
    assert miles == pytest.approx(12.1, abs=0.5)


# ── distance_penalty ────────────────────────────────────────────────────────

def test_distance_penalty_none_user_coords_is_zero():
    assert distance_penalty(None, None, 34.05, -118.24) == 0.0


def test_distance_penalty_missing_event_coords_is_zero():
    # (0.0, 0.0) is the sentinel for "no coordinates" in sparse Pinecone metadata.
    assert distance_penalty(34.05, -118.24, 0.0, 0.0) == 0.0


def test_distance_penalty_same_location_is_zero():
    assert distance_penalty(34.05, -118.24, 34.05, -118.24) == pytest.approx(0.0, abs=1e-6)


def test_distance_penalty_saturates_at_max():
    # An event far beyond the reference distance gets the maximum penalty.
    penalty = distance_penalty(34.05, -118.24, 40.71, -74.01)  # NYC, far over reference
    assert penalty == pytest.approx(DISTANCE_WEIGHT)


def test_distance_penalty_scales_with_distance():
    near = distance_penalty(34.05, -118.24, 34.10, -118.24)
    far = distance_penalty(34.05, -118.24, 34.20, -118.24)
    assert 0.0 < near < far <= DISTANCE_WEIGHT


# ── score_events: score_breakdown ───────────────────────────────────────────

_Q = [1.0, 0.0, 0.0]
_T = [0.0, 1.0, 0.0]


def _make_event(event_id: str, lat: float = 0.0, lng: float = 0.0) -> EventSchema:
    return {
        "id": event_id,
        "title": event_id,
        "description": "",
        "category": "Music",
        "tags": [],
        "vibe_tags": [],
        "venue_name": "Venue",
        "address": "",
        "city": "LA",
        "latitude": lat,
        "longitude": lng,
        "price_min": 0.0,
        "price_max": 0.0,
        "start_time": "",
        "end_time": None,
        "image_url": None,
        "source_url": "",
    }


def test_score_events_attaches_all_breakdown_components():
    evt = _make_event("a")
    ranked = score_events(_Q, _T, [evt], {"a": [1.0, 0.0, 0.0]})
    b = ranked[0]["score_breakdown"]
    assert b["query_sim"] == pytest.approx(1.0)
    assert b["taste_sim"] == pytest.approx(0.0)
    assert b["distance_penalty"] == 0.0
    assert b["final_score"] == pytest.approx(0.7)


def test_score_events_taste_sim_zero_when_no_taste_vector():
    evt = _make_event("a")
    ranked = score_events(_Q, None, [evt], {"a": [1.0, 0.0, 0.0]})
    b = ranked[0]["score_breakdown"]
    assert b["taste_sim"] == 0.0
    assert b["query_sim"] == pytest.approx(1.0)
    assert b["final_score"] == pytest.approx(1.0)


def test_score_events_top_level_score_equals_final_score():
    evt = _make_event("a")
    ranked = score_events(_Q, _T, [evt], {"a": [0.6, 0.8, 0.0]})
    assert ranked[0]["score"] == pytest.approx(ranked[0]["score_breakdown"]["final_score"])


def test_score_events_no_user_coords_final_equals_blended():
    # Backward-compat: without user location, distance_penalty is 0 and
    # final_score == QUERY_WEIGHT*query_sim + TASTE_WEIGHT*taste_sim (old score).
    evt = _make_event("a")
    ranked = score_events(_Q, _T, [evt], {"a": [0.6, 0.8, 0.0]})
    b = ranked[0]["score_breakdown"]
    expected = QUERY_WEIGHT * b["query_sim"] + TASTE_WEIGHT * b["taste_sim"]
    assert b["distance_penalty"] == 0.0
    assert b["final_score"] == pytest.approx(expected)


def test_score_events_distance_penalty_reorders_ranking():
    # Two equally relevant events; the closer one wins once the user shares coords.
    near = _make_event("near", lat=34.05, lng=-118.24)   # Los Angeles
    far = _make_event("far", lat=36.16, lng=-115.14)     # Las Vegas
    vecs = {"near": [1.0, 0.0, 0.0], "far": [1.0, 0.0, 0.0]}

    # No coords: equal final_score, both present.
    no_coords = score_events(_Q, None, [far, near], vecs)
    assert {e["id"] for e in no_coords} == {"near", "far"}

    # With coords: near must outrank far.
    ranked = score_events(_Q, None, [far, near], vecs, user_lat=34.05, user_lng=-118.24)
    assert ranked[0]["id"] == "near"
