import pytest
from unittest.mock import patch, AsyncMock
from agent.nodes import retrieve_events, hydrate_events, score_and_rank

BASE_STATE = {
    "query": "chill outdoor event this weekend",
    "semantic_query": "chill outdoor event this weekend",
    "filters": {},
    "query_vector": None,
    "candidate_events": [],
    "ranked_events": [],
    "response": None,
}


@pytest.mark.anyio
@patch(
    "agent.nodes.search_events",
    return_value=[
        {
            "id": "evt-001",
            "score": 0.95,
            "metadata": {
                "title": "Jazz Night",
                "venue_name": "The Rooftop",
                "city": "Los Angeles",
                "category": "Music",
                "tags": ["outdoor"],
                "price_min": 15.0,
                "price_max": 15.0,
                "latitude": 34.04,
                "longitude": -118.23,
            },
        }
    ],
)
@patch("agent.nodes.embed_query", return_value=[0.1] * 1536)
async def test_retrieve_events_sets_query_vector(mock_embed, mock_search):
    result = await retrieve_events(BASE_STATE)
    assert result["query_vector"] == [0.1] * 1536


@pytest.mark.anyio
@patch(
    "agent.nodes.search_events",
    return_value=[
        {
            "id": "evt-001",
            "score": 0.95,
            "metadata": {
                "title": "Jazz Night",
                "venue_name": "The Rooftop",
                "city": "Los Angeles",
                "category": "Music",
                "tags": ["outdoor"],
                "price_min": 15.0,
                "price_max": 15.0,
                "latitude": 34.04,
                "longitude": -118.23,
            },
        }
    ],
)
@patch("agent.nodes.embed_query", return_value=[0.1] * 1536)
async def test_retrieve_events_populates_candidates_from_pinecone(mock_embed, mock_search):
    result = await retrieve_events(BASE_STATE)
    assert len(result["candidate_events"]) == 1
    event = result["candidate_events"][0]
    assert event["id"] == "evt-001"
    assert event["title"] == "Jazz Night"
    assert event["venue_name"] == "The Rooftop"
    assert event["price_min"] == 15.0


@pytest.mark.anyio
@patch("agent.nodes.search_events", return_value=[])
@patch("agent.nodes.embed_query", return_value=[0.0] * 1536)
async def test_retrieve_events_empty_pinecone_returns_empty_candidates(mock_embed, mock_search):
    result = await retrieve_events(BASE_STATE)
    assert result["candidate_events"] == []


@pytest.mark.anyio
@patch(
    "agent.nodes.search_events",
    return_value=[
        {
            "id": "evt-002",
            "score": 0.80,
            "metadata": {
                "title": "Art Walk",
                "venue_name": "Arts District",
                "city": "Los Angeles",
                "category": "Art & Culture",
                "tags": ["free"],
                "price_min": 0.0,
                "price_max": 0.0,
                "latitude": 34.04,
                "longitude": -118.23,
            },
        }
    ],
)
@patch("agent.nodes.embed_query", return_value=[0.2] * 1536)
async def test_retrieve_events_passes_filters_to_search(mock_embed, mock_search):
    # parse_intent emits raw values; retrieve_events translates them into Pinecone's
    # MongoDB-style filter operators before calling search_events. A budget ceiling
    # of price_max=0 means "free", which maps to price_max == 0 (not $lte).
    state_with_filters = {
        **BASE_STATE,
        "filters": {"price_max": 0, "categories": ["Music"], "tags": ["outdoor"]},
    }
    await retrieve_events(state_with_filters)
    # Destructure so additional positional args (top_k, time_mode) don't break
    # the assertion. price_max=0 → "free" → $eq:0 per _price_filter.
    vector_arg, filter_arg, *rest = mock_search.call_args.args
    assert vector_arg == [0.2] * 1536
    assert filter_arg == {
        "price_max": {"$eq": 0},
        "category": {"$in": ["Music"]},
        "tags": {"$in": ["outdoor"]},
    }
    # Default-path retrieve_events also passes top_k=40 and time_mode="upcoming".
    assert rest == [40, "upcoming"]


@pytest.mark.anyio
async def test_hydrate_events_calls_backend_and_merges():
    # hydrate_events fetches full rows from the backend over httpx
    # (GET /events/by-ids) and merges them onto the sparse Pinecone candidates.
    from unittest.mock import MagicMock, AsyncMock
    from datetime import datetime, timedelta
    import uuid

    test_id = str(uuid.uuid4())
    # Future start_time so the unconditional time filter in hydrate_events
    # accepts the merged row (otherwise events with no start_time are dropped).
    future = (datetime.now() + timedelta(hours=2)).isoformat()
    full_row = {
        "id": test_id,
        "title": "DB Title",
        "description": "Real description",
        "category": "Music",
        "tags": ["outdoor"],
        "vibe_tags": ["chill"],
        "venue_name": "Test Venue",
        "address": "Test Venue",
        "city": "Los Angeles",
        "latitude": None,
        "longitude": None,
        "price_min": 10.0,
        "price_max": 10.0,
        "start_time": future,
        "end_time": None,  # falls back to start + 3h via _passes_time_filter
        "image_url": None,
        "source_url": "",
    }

    # hydrate_events calls GET /events/by-ids via httpx; patch the AsyncClient.
    # full_row carries a future start_time so the unconditional time filter in
    # hydrate_events doesn't drop the merged row.
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value=[full_row])
    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    state = {
        "candidate_events": [
            {"id": test_id, "title": "Sparse Title", "latitude": 34.05, "longitude": -118.25}
        ]
    }

    with patch("agent.nodes.httpx.AsyncClient", return_value=mock_client):
        result = await hydrate_events(state)

    assert len(result["hydrated_events"]) == 1
    assert result["hydrated_events"][0]["description"] == "Real description"
    assert result["hydrated_events"][0]["title"] == "DB Title"
    # lat/lng from the candidate (Pinecone metadata) survive when Supabase returns None.
    assert result["hydrated_events"][0]["latitude"] == 34.05


_SCORE_BASE_STATE = {
    "query": "chill outdoor event",
    "semantic_query": "chill outdoor event",
    "filters": {},
    "query_vector": [1.0, 0.0] + [0.0] * 1534,
    "hydrated_events": [
        {
            "id": "evt-a",
            "title": "Top Pick",
            "description": "",
            "category": "Music",
            "tags": [],
            "vibe_tags": [],
            "venue_name": "Venue A",
            "address": "",
            "city": "LA",
            "latitude": 0.0,
            "longitude": 0.0,
            "price_min": 20.0,
            "price_max": 20.0,
            "start_time": "2026-05-10T19:00:00Z",
            "end_time": None,
            "image_url": None,
            "source_url": "",
        },
        {
            "id": "evt-b",
            "title": "Lower Pick",
            "description": "",
            "category": "Comedy",
            "tags": [],
            "vibe_tags": [],
            "venue_name": "Venue B",
            "address": "",
            "city": "LA",
            "latitude": 0.0,
            "longitude": 0.0,
            "price_min": 5.0,
            "price_max": 5.0,
            "start_time": "2026-05-10T19:00:00Z",
            "end_time": None,
            "image_url": None,
            "source_url": "",
        },
    ],
    "ranked_events": [],
    "response": None,
    "user_profile": None,
    "taste_vector": None,
}


@pytest.mark.anyio
@patch(
    "agent.nodes.fetch_vectors",
    return_value={
        "evt-a": [1.0, 0.0] + [0.0] * 1534,  # aligns with query_vector
        "evt-b": [0.0, 1.0] + [0.0] * 1534,  # orthogonal to query_vector
    },
)
async def test_score_and_rank_orders_by_cosine_not_price(mock_fetch):
    # evt-b is cheaper ($5) but evt-a aligns with query — should rank first
    result = await score_and_rank(_SCORE_BASE_STATE)
    assert result["ranked_events"][0]["id"] == "evt-a"
    assert result["ranked_events"][1]["id"] == "evt-b"


@pytest.mark.anyio
@patch("agent.nodes.fetch_vectors", return_value={})
async def test_score_and_rank_empty_candidates_returns_empty(mock_fetch):
    result = await score_and_rank({**_SCORE_BASE_STATE, "hydrated_events": []})
    assert result["ranked_events"] == []


@pytest.mark.anyio
@patch(
    "agent.nodes.fetch_vectors",
    return_value={"evt-a": [1.0, 0.0] + [0.0] * 1534},
)
async def test_score_and_rank_sets_response_string(mock_fetch):
    state = {
        **_SCORE_BASE_STATE,
        "hydrated_events": [_SCORE_BASE_STATE["hydrated_events"][0]],
    }
    result = await score_and_rank(state)
    assert "Top Pick" in result["response"]
    assert "Venue A" in result["response"]


@pytest.mark.anyio
@patch(
    "agent.nodes.fetch_vectors",
    return_value={
        "evt-a": [1.0, 0.0] + [0.0] * 1534,  # aligns with query
        "evt-b": [0.0, 1.0] + [0.0] * 1534,  # aligns with taste
    },
)
async def test_score_and_rank_uses_taste_vector_when_present(mock_fetch):
    # With query=[1,0,...] and taste=[0,1,...]:
    # evt-a: 0.7*1.0 + 0.3*0.0 = 0.70 → ranks first
    # evt-b: 0.7*0.0 + 0.3*1.0 = 0.30 → ranks second
    state = {
        **_SCORE_BASE_STATE,
        "taste_vector": [0.0, 1.0] + [0.0] * 1534,
    }
    result = await score_and_rank(state)
    assert result["ranked_events"][0]["id"] == "evt-a"
    assert result["ranked_events"][1]["id"] == "evt-b"


@pytest.mark.anyio
@patch(
    "agent.nodes.fetch_vectors",
    return_value={
        "evt-a": [1.0, 0.0] + [0.0] * 1534,
        "evt-b": [0.0, 1.0] + [0.0] * 1534,
    },
)
async def test_score_and_rank_populates_enriched_events_with_breakdown(mock_fetch):
    result = await score_and_rank(_SCORE_BASE_STATE)
    enriched = result["enriched_events"]
    assert len(enriched) == 2
    for event in enriched:
        assert set(event["score_breakdown"]) == {
            "query_sim",
            "taste_sim",
            "distance_penalty",
            "final_score",
        }
        assert event["score"] == event["score_breakdown"]["final_score"]


@pytest.mark.anyio
@patch(
    "agent.nodes.fetch_vectors",
    return_value={
        # Identical vectors → only the distance penalty can break the tie.
        "evt-a": [1.0, 0.0] + [0.0] * 1534,
        "evt-b": [1.0, 0.0] + [0.0] * 1534,
    },
)
async def test_score_and_rank_threads_user_coords_into_distance(mock_fetch):
    state = {
        **_SCORE_BASE_STATE,
        "query_vector": [1.0, 0.0] + [0.0] * 1534,
        "taste_vector": None,
        "hydrated_events": [
            {**_SCORE_BASE_STATE["hydrated_events"][0], "id": "evt-a",
             "latitude": 36.16, "longitude": -115.14},   # Las Vegas (far)
            {**_SCORE_BASE_STATE["hydrated_events"][1], "id": "evt-b",
             "latitude": 34.05, "longitude": -118.24},   # Los Angeles (near)
        ],
        "user_lat": 34.05,
        "user_lng": -118.24,
    }
    result = await score_and_rank(state)
    # With identical semantic relevance, the nearer event must win once the node
    # threads the user's coordinates into score_events.
    assert result["enriched_events"][0]["id"] == "evt-b"
    assert result["enriched_events"][0]["score_breakdown"]["distance_penalty"] == 0.0
    assert result["enriched_events"][1]["score_breakdown"]["distance_penalty"] > 0.0
