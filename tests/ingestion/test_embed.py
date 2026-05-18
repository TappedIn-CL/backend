from unittest.mock import patch
from ingestion.embed import embed_and_upsert

VALID_EVENT = {
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
    "end_time": None,
    "image_url": None,
    "source_url": "https://example.com",
}


def test_returns_zero_for_empty_list():
    assert embed_and_upsert([]) == 0


@patch("ingestion.embed.upsert_events", return_value=1)
def test_passes_valid_events_to_upsert(mock_upsert):
    count = embed_and_upsert([VALID_EVENT])
    assert count == 1
    mock_upsert.assert_called_once_with([VALID_EVENT])


@patch("ingestion.embed.upsert_events", return_value=0)
def test_skips_event_with_missing_required_fields(mock_upsert):
    bad_event = {"id": "evt-bad", "title": "Missing Fields"}
    count = embed_and_upsert([bad_event])
    assert count == 0
    mock_upsert.assert_called_once_with([])


@patch("ingestion.embed.upsert_events", return_value=1)
def test_filters_invalid_keeps_valid(mock_upsert):
    bad_event = {"id": "evt-bad", "title": "No category"}
    count = embed_and_upsert([VALID_EVENT, bad_event])
    assert count == 1
    mock_upsert.assert_called_once_with([VALID_EVENT])


@patch("ingestion.embed.upsert_events", return_value=0)
def test_skips_event_with_none_required_field(mock_upsert):
    none_event = {**VALID_EVENT, "category": None}
    count = embed_and_upsert([none_event])
    assert count == 0
    mock_upsert.assert_called_once_with([])
