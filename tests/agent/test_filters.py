"""
End-to-end tests for the FilterModal -> agent filter pipeline.

Covers the path a UI filter selection travels:
  request ui_filters  ->  AgentQueryRequest (schema)
                      ->  _merge_ui_filters  (UI overrides LLM-parsed filters)
                      ->  _to_pinecone_filter (Mongo-style metadata operators)
                      ->  search_events / upcoming_only_filter (the actual query)

and the chip pipeline (chips fold into the embedded query + category filter in
parse_intent). Three layers:
  1. pure translation functions (no I/O)
  2. node integration (retrieve_events / parse_intent with mocked boundaries)
  3. full graph run (agent.ainvoke) with every external boundary mocked
"""

import json
import time
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent.nodes import (
    _iso_date_to_unix,
    _merge_ui_filters,
    _price_filter,
    _to_pinecone_filter,
    parse_intent,
    retrieve_events,
)
from agent.pinecone_client import upcoming_only_filter
from agent.graph import agent
from schemas.agent import AgentQueryRequest


# ──────────────────────────────────────────────────────────────────────────
# Layer 1 — pure translation: _price_filter (overlap + free semantics)
# ──────────────────────────────────────────────────────────────────────────

def test_price_untouched_slider_adds_nothing():
    assert _price_filter({}) == {}


def test_price_free_toggle_maps_to_exact_zero():
    assert _price_filter({"show_free_only": True}) == {"price_max": {"$eq": 0}}


def test_price_zero_ceiling_means_free_not_overlap():
    # A $0 budget ceiling (slider dragged to 0, or LLM "free") == truly free.
    assert _price_filter({"price_max": 0}) == {"price_max": {"$eq": 0}}


def test_price_upper_bound_constrains_event_min():
    # The filter's MAX constrains the event's MIN (cheapest tier <= ceiling).
    assert _price_filter({"price_max": 50}) == {"price_min": {"$lte": 50}}


def test_price_lower_bound_constrains_event_max():
    # The filter's MIN constrains the event's MAX (top tier >= floor).
    assert _price_filter({"price_min": 20}) == {"price_max": {"$gte": 20}}


def test_price_band_is_interval_intersection():
    assert _price_filter({"price_min": 20, "price_max": 80}) == {
        "price_min": {"$lte": 80},
        "price_max": {"$gte": 20},
    }


def test_price_free_toggle_overrides_a_set_band():
    assert _price_filter({"price_min": 20, "price_max": 80, "show_free_only": True}) == {
        "price_max": {"$eq": 0}
    }


# ──────────────────────────────────────────────────────────────────────────
# Layer 1 — pure translation: _iso_date_to_unix
# ──────────────────────────────────────────────────────────────────────────

def test_iso_date_midnight_vs_end_of_day():
    midnight = _iso_date_to_unix("2026-06-15")
    end = _iso_date_to_unix("2026-06-15", end_of_day=True)
    assert end - midnight == 86399  # 23:59:59 of the same day


def test_iso_date_bad_input_returns_none():
    assert _iso_date_to_unix("not-a-date") is None
    assert _iso_date_to_unix(None) is None  # type: ignore[arg-type]


# ──────────────────────────────────────────────────────────────────────────
# Layer 1 — pure translation: _merge_ui_filters (UI overrides LLM)
# ──────────────────────────────────────────────────────────────────────────

def test_merge_none_ui_is_noop():
    llm = {"categories": ["Music"], "price_max": 25}
    assert _merge_ui_filters(llm, None) == llm


def test_merge_ui_category_overrides_llm():
    merged = _merge_ui_filters({"categories": ["Music"]}, {"category": "Arts"})
    assert merged["categories"] == ["Arts"]


def test_merge_category_all_keeps_llm_inference():
    merged = _merge_ui_filters({"categories": ["Music"]}, {"category": "All"})
    assert merged["categories"] == ["Music"]


def test_merge_carries_price_free_and_dates():
    merged = _merge_ui_filters(
        {},
        {
            "price_min": 20,
            "price_max": 80,
            "show_free_only": True,
            "date_from": "2026-06-10",
            "date_to": "2026-06-20",
        },
    )
    assert merged["price_min"] == 20
    assert merged["price_max"] == 80
    assert merged["show_free_only"] is True
    assert merged["date_from"] == "2026-06-10"
    assert merged["date_to"] == "2026-06-20"


# ──────────────────────────────────────────────────────────────────────────
# Layer 1 — pure translation: _to_pinecone_filter (full composition)
# ──────────────────────────────────────────────────────────────────────────

def test_to_pinecone_composes_price_category_tags_dates():
    f = _to_pinecone_filter(
        {
            "price_min": 20,
            "price_max": 80,
            "categories": ["Arts"],
            "tags": ["outdoor"],
            "date_from": "2026-06-10",
            "date_to": "2026-06-20",
        }
    )
    assert f["price_min"] == {"$lte": 80}
    assert f["price_max"] == {"$gte": 20}
    assert f["category"] == {"$in": ["Arts"]}
    assert f["tags"] == {"$in": ["outdoor"]}
    assert f["start_time_unix"]["$gte"] == _iso_date_to_unix("2026-06-10")
    assert f["start_time_unix"]["$lte"] == _iso_date_to_unix("2026-06-20", end_of_day=True)


def test_to_pinecone_empty_filters_is_empty():
    assert _to_pinecone_filter({}) == {}


# ──────────────────────────────────────────────────────────────────────────
# Layer 1 — upcoming_only_filter merges date range with the "not started" floor
# ──────────────────────────────────────────────────────────────────────────

def test_upcoming_floor_when_no_extra():
    f = upcoming_only_filter()
    assert f["start_time_unix"]["$gte"] <= int(time.time())
    assert "$lte" not in f["start_time_unix"]


def test_upcoming_preserves_other_keys():
    f = upcoming_only_filter({"category": {"$in": ["Arts"]}})
    assert f["category"] == {"$in": ["Arts"]}
    assert "start_time_unix" in f


def test_upcoming_floors_a_past_date_from_to_now():
    now = int(time.time())
    past, future = now - 100_000, now + 100_000
    f = upcoming_only_filter({"start_time_unix": {"$gte": past, "$lte": future}})
    # past lower bound is raised to ~now so already-started events can't leak in
    assert f["start_time_unix"]["$gte"] >= now - 2
    assert f["start_time_unix"]["$lte"] == future


def test_upcoming_keeps_a_future_date_from():
    now = int(time.time())
    future_from, future_to = now + 100_000, now + 200_000
    f = upcoming_only_filter({"start_time_unix": {"$gte": future_from, "$lte": future_to}})
    assert f["start_time_unix"]["$gte"] == future_from
    assert f["start_time_unix"]["$lte"] == future_to


# ──────────────────────────────────────────────────────────────────────────
# Layer 0 — request schema parses ui_filters and ignores extra fields
# ──────────────────────────────────────────────────────────────────────────

def test_schema_parses_ui_filters_and_latlng_together():
    # user_lat/user_lng are modeled on the request (distance scoring needs them);
    # ui_filters lives alongside them. This test guards that both pipelines stay
    # wired through the same payload without one clobbering the other.
    req = AgentQueryRequest.model_validate(
        {
            "query": "art events",
            "chips": ["Foodie"],
            "user_lat": 34.07,
            "user_lng": -118.44,
            "ui_filters": {
                "category": "Arts",
                "price_min": 20,
                "price_max": 80,
                "show_free_only": False,
                "date_from": "2026-06-10",
                "date_to": "2026-06-20",
            },
        }
    )
    assert req.ui_filters.category == "Arts"
    assert req.ui_filters.date_from == "2026-06-10"
    assert req.user_lat == 34.07
    assert req.user_lng == -118.44


def test_schema_ui_filters_optional():
    assert AgentQueryRequest.model_validate({"query": "x"}).ui_filters is None


# ──────────────────────────────────────────────────────────────────────────
# Layer 2 — retrieve_events: the merged filter actually reaches search_events
# ──────────────────────────────────────────────────────────────────────────

_RETRIEVE_STATE = {
    "query": "events",
    "semantic_query": "events",
    "query_vector": [0.2] * 1536,  # set so embed_query isn't called
    "filters": {},
    "ui_filters": None,
    "candidate_events": [],
}


def _captured_filter(mock_search):
    """search_events(vector, filter, over_fetch) — pull the filter arg."""
    return mock_search.call_args.args[1]


@pytest.mark.anyio
@patch("agent.nodes.search_events", return_value=[])
async def test_retrieve_ui_category_overrides_llm(mock_search):
    await retrieve_events(
        {**_RETRIEVE_STATE, "filters": {"categories": ["Music"]}, "ui_filters": {"category": "Arts"}}
    )
    assert _captured_filter(mock_search)["category"] == {"$in": ["Arts"]}


@pytest.mark.anyio
@patch("agent.nodes.search_events", return_value=[])
async def test_retrieve_price_band_reaches_query(mock_search):
    await retrieve_events(
        {**_RETRIEVE_STATE, "ui_filters": {"price_min": 20, "price_max": 80}}
    )
    f = _captured_filter(mock_search)
    assert f["price_min"] == {"$lte": 80}
    assert f["price_max"] == {"$gte": 20}


@pytest.mark.anyio
@patch("agent.nodes.search_events", return_value=[])
async def test_retrieve_free_only_reaches_query(mock_search):
    await retrieve_events({**_RETRIEVE_STATE, "ui_filters": {"show_free_only": True}})
    assert _captured_filter(mock_search) == {"price_max": {"$eq": 0}}


@pytest.mark.anyio
@patch("agent.nodes.search_events", return_value=[])
async def test_retrieve_date_range_reaches_query(mock_search):
    await retrieve_events(
        {**_RETRIEVE_STATE, "ui_filters": {"date_from": "2026-06-10", "date_to": "2026-06-20"}}
    )
    rng = _captured_filter(mock_search)["start_time_unix"]
    assert rng["$gte"] == _iso_date_to_unix("2026-06-10")
    assert rng["$lte"] == _iso_date_to_unix("2026-06-20", end_of_day=True)


@pytest.mark.anyio
@patch("agent.nodes.search_events", return_value=[])
async def test_retrieve_no_ui_filters_uses_llm_only(mock_search):
    await retrieve_events({**_RETRIEVE_STATE, "filters": {"categories": ["Comedy"]}})
    assert _captured_filter(mock_search) == {"category": {"$in": ["Comedy"]}}


# ──────────────────────────────────────────────────────────────────────────
# Layer 2 — parse_intent folds selected chips into query + category filter
# ──────────────────────────────────────────────────────────────────────────

def _fake_chat_client(content: str):
    """Minimal stand-in for the OpenAI async client used by parse_intent."""
    async def _create(**kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_create)))


_LLM_JSON = json.dumps(
    {
        "semantic_query": "live music",
        "filters": {
            "categories": ["Music"],
            "price_max": None,
            "max_distance": None,
            "age_restrictions": None,
            "vibes": [],
            "tags": [],
        },
    }
)


@pytest.mark.anyio
@patch("agent.nodes.embed_query", return_value=[0.1] * 1536)
@patch("agent.nodes._get_chat_client")
async def test_parse_intent_chips_enrich_query_and_categories(mock_client, mock_embed):
    mock_client.return_value = _fake_chat_client(_LLM_JSON)
    result = await parse_intent({"query": "concerts", "chips": ["Foodie", "Cozy"]})
    # chip semantic_phrases are appended to the text that gets embedded
    assert "foodie dining culinary" in result["semantic_query"]
    assert "cozy warm intimate relaxed" in result["semantic_query"]
    # chip categories are unioned onto the LLM-inferred categories
    assert result["filters"]["categories"] == ["Music", "Food & Drink"]


@pytest.mark.anyio
@patch("agent.nodes.embed_query", return_value=[0.1] * 1536)
@patch("agent.nodes._get_chat_client", side_effect=RuntimeError("LLM down"))
async def test_parse_intent_chips_apply_even_when_llm_fails(mock_client, mock_embed):
    result = await parse_intent({"query": "concerts", "chips": ["Music", "Happening Now"]})
    # falls back to raw query, but chips still enrich it ("Happening Now" ignored)
    assert "music live performance concert" in result["semantic_query"]
    assert result["filters"]["categories"] == ["Music"]


# ──────────────────────────────────────────────────────────────────────────
# Layer 3 — full graph run: ui_filters + chips -> correct query -> ranked out
# ──────────────────────────────────────────────────────────────────────────

class _FakeResp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


class _FakeAsyncClient:
    """Stand-in for httpx.AsyncClient used by hydrate_events."""
    def __init__(self, rows):
        self._rows = rows

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, params=None):
        return _FakeResp(self._rows)


_MATCHES = [
    {
        "id": "evt-a",
        "score": 0.9,
        "metadata": {
            "title": "Gallery Opening", "venue_name": "Arts District", "city": "LA",
            "category": "Arts", "tags": [], "price_min": 10.0, "price_max": 10.0,
            "latitude": 34.04, "longitude": -118.23,
        },
    },
    {
        "id": "evt-b",
        "score": 0.8,
        "metadata": {
            "title": "Mural Tour", "venue_name": "Downtown", "city": "LA",
            "category": "Arts", "tags": [], "price_min": 25.0, "price_max": 25.0,
            "latitude": 34.05, "longitude": -118.24,
        },
    },
]
# Future start_time on every row so hydrate_events' unconditional time filter
# (drops events that have already ended) doesn't strip them before scoring.
_FUTURE_START = (datetime.now() + timedelta(hours=2)).isoformat()
_HYDRATION_ROWS = [
    {"id": "evt-a", "title": "Gallery Opening", "description": "desc a",
     "latitude": None, "longitude": None, "start_time": _FUTURE_START, "end_time": None},
    {"id": "evt-b", "title": "Mural Tour", "description": "desc b",
     "latitude": None, "longitude": None, "start_time": _FUTURE_START, "end_time": None},
]
_QUERY_VEC = [1.0, 0.0] + [0.0] * 1534
_EVENT_VECS = {
    "evt-a": [1.0, 0.0] + [0.0] * 1534,  # aligned with query -> ranks first
    "evt-b": [0.0, 1.0] + [0.0] * 1534,  # orthogonal -> ranks second
}


@pytest.mark.anyio
async def test_full_graph_ui_filters_and_chips_end_to_end():
    seed = {
        "query": "things to do", "chips": ["Foodie"],
        "semantic_query": "", "filters": {},
        "ui_filters": {"category": "Arts", "price_max": 50},
        "query_vector": None, "candidate_events": [], "hydrated_events": [],
        "ranked_events": [], "response": None, "user_profile": None, "taste_vector": None,
    }

    with patch("agent.nodes._get_chat_client", return_value=_fake_chat_client(_LLM_JSON)), \
         patch("agent.nodes.embed_query", return_value=_QUERY_VEC), \
         patch("agent.nodes.search_events", return_value=_MATCHES) as mock_search, \
         patch("agent.nodes.httpx.AsyncClient", lambda *a, **k: _FakeAsyncClient(_HYDRATION_ROWS)), \
         patch("agent.nodes.fetch_vectors", return_value=_EVENT_VECS):
        result = await agent.ainvoke(seed)

    # 1. The query that hit Pinecone carried the UI filters.
    sent_filter = mock_search.call_args.args[1]
    # UI "Arts" overrides both the LLM ("Music") and the chip ("Foodie"->Food & Drink)
    assert sent_filter["category"] == {"$in": ["Arts"]}
    # price ceiling 50 -> event's cheapest tier <= 50 (overlap)
    assert sent_filter["price_min"] == {"$lte": 50}

    # 2. The chip enriched the embedded query text.
    assert "foodie dining culinary" in result["semantic_query"]

    # 3. Results flowed through hydrate + score and came out ranked.
    ranked = result["ranked_events"]
    assert [e["id"] for e in ranked] == ["evt-a", "evt-b"]
    assert ranked[0]["description"] == "desc a"  # hydration merged in
