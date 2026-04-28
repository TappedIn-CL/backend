from unittest.mock import patch
from agent.nodes import retrieve_events

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
