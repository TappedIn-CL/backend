import time
from unittest.mock import patch, MagicMock
from agent.pinecone_client import (
    _build_record,
    upsert_events,
    search_events,
    fetch_vectors,
    delete_vectors,
    upcoming_only_filter,
    happening_now_filter,
    DEFAULT_EVENT_DURATION_HOURS,
    HAPPENING_NOW_LOOKBACK_SECONDS,
)

MOCK_EVENT = {
    "id": "evt-001",
    "title": "Test Event",
    "description": "A test event",
    "category": "Music",
    "tags": ["outdoor"],
    "vibe_tags": ["chill"],
    "venue_name": "Test Venue",
    "address": "123 Main St",
    "city": "Los Angeles",
    "latitude": 34.05,
    "longitude": -118.25,
    "price_min": 10.0,
    "price_max": 10.0,
    "start_time": "2026-05-01T19:00:00Z",
    "end_time": "2026-05-01T23:00:00Z",
    "image_url": None,
    "source_url": "https://example.com",
}


def test_build_record_shape():
    vector = [0.1] * 1536
    record = _build_record(MOCK_EVENT, vector)
    assert record["id"] == "evt-001"
    assert record["values"] == vector
    assert record["metadata"]["title"] == "Test Event"
    assert record["metadata"]["venue_name"] == "Test Venue"
    assert record["metadata"]["city"] == "Los Angeles"
    assert record["metadata"]["price_min"] == 10.0
    assert record["metadata"]["price_max"] == 10.0
    assert record["metadata"]["tags"] == ["outdoor"]
    assert isinstance(record["metadata"]["start_time_unix"], int)
    assert record["metadata"]["start_time_unix"] > 0
    # MOCK_EVENT has end_time → end_time_unix derived from it (4-hour event).
    assert isinstance(record["metadata"]["end_time_unix"], int)
    assert record["metadata"]["end_time_unix"] - record["metadata"]["start_time_unix"] == 4 * 3600


def test_build_record_defaults_end_time_when_missing():
    """When a source omits end_time, fall back to start + DEFAULT_EVENT_DURATION_HOURS.
    Mirrors effective_end_time semantics so all three layers (ingest, query,
    hydrate) agree on when an event is 'over'."""
    event = {**MOCK_EVENT, "end_time": None}
    record = _build_record(event, [0.1] * 1536)
    delta = record["metadata"]["end_time_unix"] - record["metadata"]["start_time_unix"]
    assert delta == DEFAULT_EVENT_DURATION_HOURS * 3600


@patch("agent.pinecone_client._get_index")
@patch("agent.pinecone_client.embed_event", return_value=[0.1] * 1536)
def test_upsert_events_returns_count(mock_embed, mock_get_index):
    mock_index = MagicMock()
    mock_get_index.return_value = mock_index
    count = upsert_events([MOCK_EVENT])
    assert count == 1
    mock_index.upsert.assert_called_once()


@patch("agent.pinecone_client._get_index")
@patch("agent.pinecone_client.embed_event", return_value=[0.1] * 1536)
def test_upsert_events_batches_at_100(mock_embed, mock_get_index):
    mock_index = MagicMock()
    mock_get_index.return_value = mock_index
    events = [{**MOCK_EVENT, "id": f"evt-{i:03d}"} for i in range(250)]
    count = upsert_events(events)
    assert count == 250
    assert mock_index.upsert.call_count == 3  # 100 + 100 + 50


@patch("agent.pinecone_client._get_index")
@patch("agent.pinecone_client.embed_event", side_effect=Exception("OpenAI error"))
def test_upsert_events_skips_failed_embeds(mock_embed, mock_get_index):
    mock_index = MagicMock()
    mock_get_index.return_value = mock_index
    count = upsert_events([MOCK_EVENT])
    assert count == 0
    mock_index.upsert.assert_not_called()


@patch("agent.pinecone_client._get_index")
def test_search_events_returns_matches(mock_get_index):
    mock_index = MagicMock()
    mock_index.query.return_value = {
        "matches": [
            {
                "id": "evt-001",
                "score": 0.95,
                "metadata": {"title": "Test Event", "price_min": 10.0},
            }
        ]
    }
    mock_get_index.return_value = mock_index
    results = search_events([0.1] * 1536, {}, top_k=5)
    assert len(results) == 1
    assert results[0]["id"] == "evt-001"
    assert results[0]["score"] == 0.95
    assert results[0]["metadata"]["title"] == "Test Event"


@patch("agent.pinecone_client._get_index")
def test_search_events_always_applies_upcoming_filter(mock_get_index):
    mock_index = MagicMock()
    mock_index.query.return_value = {"matches": []}
    mock_get_index.return_value = mock_index
    search_events([0.1] * 1536, {}, top_k=5)
    call_kwargs = mock_index.query.call_args[1]
    assert call_kwargs["filter"] == upcoming_only_filter()


@patch("agent.pinecone_client._get_index")
def test_search_events_merges_user_filters_with_upcoming(mock_get_index):
    mock_index = MagicMock()
    mock_index.query.return_value = {"matches": []}
    mock_get_index.return_value = mock_index
    search_events([0.1] * 1536, {"city": "Los Angeles"}, top_k=5)
    call_kwargs = mock_index.query.call_args[1]
    assert call_kwargs["filter"]["city"] == "Los Angeles"
    assert call_kwargs["filter"]["start_time_unix"]["$gte"] <= int(time.time())


def test_happening_now_filter_window_shape():
    f = happening_now_filter()
    now = int(time.time())
    window = f["start_time_unix"]
    # Lenient window: events that started in the last 24h up to now.
    assert window["$lte"] <= now
    assert window["$gte"] >= now - HAPPENING_NOW_LOOKBACK_SECONDS - 5  # tolerance for time drift
    assert window["$lte"] - window["$gte"] == HAPPENING_NOW_LOOKBACK_SECONDS


@patch("agent.pinecone_client._get_index")
def test_search_events_uses_happening_now_filter_when_mode_set(mock_get_index):
    mock_index = MagicMock()
    mock_index.query.return_value = {"matches": []}
    mock_get_index.return_value = mock_index
    search_events([0.1] * 1536, {}, top_k=5, time_mode="happening_now")
    call_kwargs = mock_index.query.call_args[1]
    window = call_kwargs["filter"]["start_time_unix"]
    # happening_now mode wants events that already started (upper bound <= now),
    # not events that haven't started (lower bound >= now from upcoming filter).
    assert "$lte" in window
    assert window["$lte"] <= int(time.time())


@patch("agent.pinecone_client.time.sleep")
@patch("agent.pinecone_client._get_index")
@patch("agent.pinecone_client.embed_event", return_value=[0.1] * 1536)
def test_upsert_batch_retries_on_failure(mock_embed, mock_get_index, mock_sleep):
    mock_index = MagicMock()
    mock_index.upsert.side_effect = Exception("Pinecone timeout")
    mock_get_index.return_value = mock_index
    count = upsert_events([MOCK_EVENT])
    assert count == 0
    assert mock_index.upsert.call_count == 4  # 4 total attempts
    assert mock_sleep.call_count == 3  # sleep 1s, 2s, 4s between attempts


def test_fetch_vectors_returns_id_to_values_map():
    mock_vec = MagicMock()
    mock_vec.values = [0.5] * 1536
    mock_result = MagicMock()
    mock_result.vectors = {"evt-001": mock_vec}
    mock_index = MagicMock()
    mock_index.fetch.return_value = mock_result

    with patch("agent.pinecone_client._get_index", return_value=mock_index):
        result = fetch_vectors(["evt-001"])

    assert result == {"evt-001": [0.5] * 1536}
    mock_index.fetch.assert_called_once_with(ids=["evt-001"])


def test_fetch_vectors_empty_ids_returns_empty_dict():
    mock_result = MagicMock()
    mock_result.vectors = {}
    mock_index = MagicMock()
    mock_index.fetch.return_value = mock_result

    with patch("agent.pinecone_client._get_index", return_value=mock_index):
        result = fetch_vectors([])

    assert result == {}
    mock_index.fetch.assert_not_called()


@patch("agent.pinecone_client._get_index")
def test_delete_vectors_returns_count(mock_get_index):
    mock_index = MagicMock()
    mock_get_index.return_value = mock_index
    count = delete_vectors(["evt-001", "evt-002"])
    assert count == 2
    mock_index.delete.assert_called_once_with(ids=["evt-001", "evt-002"])


def test_delete_vectors_empty_ids_returns_zero_without_index():
    with patch("agent.pinecone_client._get_index") as mock_get_index:
        assert delete_vectors([]) == 0
        mock_get_index.assert_not_called()


@patch("agent.pinecone_client._get_index")
def test_delete_vectors_batches_at_1000(mock_get_index):
    mock_index = MagicMock()
    mock_get_index.return_value = mock_index
    ids = [f"evt-{i:04d}" for i in range(2500)]
    count = delete_vectors(ids)
    assert count == 2500
    assert mock_index.delete.call_count == 3  # 1000 + 1000 + 500


@patch("agent.pinecone_client._get_index")
def test_delete_vectors_skips_failed_batch_in_count(mock_get_index):
    mock_index = MagicMock()
    mock_index.delete.side_effect = Exception("Pinecone timeout")
    mock_get_index.return_value = mock_index
    count = delete_vectors(["evt-001"])
    assert count == 0


def test_fetch_vectors_multiple_ids():
    mock_a = MagicMock()
    mock_a.values = [1.0] * 1536
    mock_b = MagicMock()
    mock_b.values = [0.0] * 1536
    mock_result = MagicMock()
    mock_result.vectors = {"evt-a": mock_a, "evt-b": mock_b}
    mock_index = MagicMock()
    mock_index.fetch.return_value = mock_result

    with patch("agent.pinecone_client._get_index", return_value=mock_index):
        result = fetch_vectors(["evt-a", "evt-b"])

    assert len(result) == 2
    assert result["evt-a"] == [1.0] * 1536
    assert result["evt-b"] == [0.0] * 1536
