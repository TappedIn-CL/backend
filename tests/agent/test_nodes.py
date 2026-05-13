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
    # MongoDB-style filter operators before calling search_events.
    state_with_filters = {
        **BASE_STATE,
        "filters": {"price_max": 0, "categories": ["Music"], "tags": ["outdoor"]},
    }
    await retrieve_events(state_with_filters)
    mock_search.assert_called_once_with(
        [0.2] * 1536,
        {
            "price_max": {"$lte": 0},
            "category": {"$in": ["Music"]},
            "tags": {"$in": ["outdoor"]},
        },
        top_k=20,
    )


@pytest.mark.anyio
@patch("db.session.SessionLocal")
async def test_hydrate_events_calls_db_and_merges(mock_session_cls):
    from unittest.mock import MagicMock
    import uuid

    test_id = str(uuid.uuid4())

    mock_event = MagicMock()
    mock_event.id = uuid.UUID(test_id)
    mock_event.title = "DB Title"
    mock_event.description = "Real description"
    mock_event.category = "Music"
    mock_event.special_tags = "outdoor"
    mock_event.vibe_tags = "chill"
    mock_event.location = "Test Venue"
    mock_event.cost = 10.0
    mock_event.date = None

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.all.return_value = [mock_event]
    mock_session_cls.return_value = mock_db

    state = {
        "candidate_events": [
            {"id": test_id, "title": "Sparse Title"}
        ]
    }

    result = await hydrate_events(state)
    assert len(result["hydrated_events"]) == 1
    assert result["hydrated_events"][0]["description"] == "Real description"
    assert result["hydrated_events"][0]["title"] == "DB Title"


_SCORE_BASE_STATE = {
    "query": "chill outdoor event",
    "semantic_query": "chill outdoor event",
    "filters": {},
    "query_vector": [1.0, 0.0] + [0.0] * 1534,
    "candidate_events": [
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
    result = await score_and_rank({**_SCORE_BASE_STATE, "candidate_events": []})
    assert result["ranked_events"] == []


@pytest.mark.anyio
@patch(
    "agent.nodes.fetch_vectors",
    return_value={"evt-a": [1.0, 0.0] + [0.0] * 1534},
)
async def test_score_and_rank_sets_response_string(mock_fetch):
    state = {
        **_SCORE_BASE_STATE,
        "candidate_events": [_SCORE_BASE_STATE["candidate_events"][0]],
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
