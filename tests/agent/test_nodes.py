from unittest.mock import patch
from agent.nodes import retrieve_events, score_and_rank

BASE_STATE = {
    "query": "chill outdoor event this weekend",
    "semantic_query": "chill outdoor event this weekend",
    "filters": {},
    "query_vector": None,
    "candidate_events": [],
    "ranked_events": [],
    "response": None,
}


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
def test_retrieve_events_sets_query_vector(mock_embed, mock_search):
    result = retrieve_events(BASE_STATE)
    assert result["query_vector"] == [0.1] * 1536


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
def test_retrieve_events_populates_candidates_from_pinecone(mock_embed, mock_search):
    result = retrieve_events(BASE_STATE)
    assert len(result["candidate_events"]) == 1
    event = result["candidate_events"][0]
    assert event["id"] == "evt-001"
    assert event["title"] == "Jazz Night"
    assert event["venue_name"] == "The Rooftop"
    assert event["price_min"] == 15.0


@patch("agent.nodes.search_events", return_value=[])
@patch("agent.nodes.embed_query", return_value=[0.0] * 1536)
def test_retrieve_events_empty_pinecone_returns_empty_candidates(mock_embed, mock_search):
    result = retrieve_events(BASE_STATE)
    assert result["candidate_events"] == []


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
def test_retrieve_events_passes_filters_to_search(mock_embed, mock_search):
    state_with_filters = {**BASE_STATE, "filters": {"price_max": {"$lte": 0}}}
    retrieve_events(state_with_filters)
    mock_search.assert_called_once_with([0.2] * 1536, {"price_max": {"$lte": 0}}, top_k=20)


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


@patch(
    "agent.nodes.fetch_vectors",
    return_value={
        "evt-a": [1.0, 0.0] + [0.0] * 1534,
        "evt-b": [0.0, 1.0] + [0.0] * 1534,
    },
)
def test_score_and_rank_orders_by_cosine_not_price(mock_fetch):
    result = score_and_rank(_SCORE_BASE_STATE)
    assert result["ranked_events"][0]["id"] == "evt-a"
    assert result["ranked_events"][1]["id"] == "evt-b"


@patch("agent.nodes.fetch_vectors", return_value={})
def test_score_and_rank_empty_candidates_returns_empty(mock_fetch):
    result = score_and_rank({**_SCORE_BASE_STATE, "candidate_events": []})
    assert result["ranked_events"] == []


@patch(
    "agent.nodes.fetch_vectors",
    return_value={"evt-a": [1.0, 0.0] + [0.0] * 1534},
)
def test_score_and_rank_sets_response_string(mock_fetch):
    state = {
        **_SCORE_BASE_STATE,
        "candidate_events": [_SCORE_BASE_STATE["candidate_events"][0]],
    }
    result = score_and_rank(state)
    assert "Top Pick" in result["response"]
    assert "Venue A" in result["response"]


@patch(
    "agent.nodes.fetch_vectors",
    return_value={
        "evt-a": [1.0, 0.0] + [0.0] * 1534,
        "evt-b": [0.0, 1.0] + [0.0] * 1534,
    },
)
def test_score_and_rank_uses_taste_vector_when_present(mock_fetch):
    state = {
        **_SCORE_BASE_STATE,
        "taste_vector": [0.0, 1.0] + [0.0] * 1534,
    }
    result = score_and_rank(state)
    assert result["ranked_events"][0]["id"] == "evt-a"
    assert result["ranked_events"][1]["id"] == "evt-b"
