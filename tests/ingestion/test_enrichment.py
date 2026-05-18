import json
from unittest.mock import MagicMock, patch

from ingestion.enrichment import (
    _build_user_prompt,
    _validate_enrichment,
    enrich_event,
    enrich_events,
)


RAW_EVENT = {
    "id": "evt-001",
    "title": "Sunset Jazz at The Rooftop",
    "description": "Live jazz quartet at a converted warehouse rooftop with skyline views.",
    "venue_name": "The Rooftop DTLA",
    "address": "820 E 3rd St, Los Angeles, CA",
    "price_min": 15.0,
}


def _mock_chat_response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = json.dumps(payload)
    return response


def test_validate_enrichment_drops_unknown_tags():
    out = _validate_enrichment({
        "category": "Music",
        "tags": ["outdoor", "made-up-tag", "21+"],
        "vibe_tags": ["chill", "fake-vibe"],
    })
    assert out["category"] == "Music"
    assert out["tags"] == ["outdoor", "21+"]
    assert out["vibe_tags"] == ["chill"]


def test_validate_enrichment_falls_back_on_bad_category():
    out = _validate_enrichment({
        "category": "Wizardry",
        "tags": [],
        "vibe_tags": ["chill"],
    })
    assert out["category"] == "Other"


def test_validate_enrichment_caps_vibes_at_three():
    out = _validate_enrichment({
        "category": "Music",
        "tags": [],
        "vibe_tags": ["chill", "intimate", "social", "creative"],
    })
    assert len(out["vibe_tags"]) == 3


def test_validate_enrichment_defaults_empty_vibes_to_social():
    out = _validate_enrichment({"category": "Music", "tags": [], "vibe_tags": []})
    assert out["vibe_tags"] == ["social"]


def test_build_user_prompt_handles_missing_fields():
    prompt = _build_user_prompt({"title": "", "description": "", "venue_name": ""})
    assert "(no title)" in prompt
    assert "(no description)" in prompt
    assert "(no venue)" in prompt


@patch("ingestion.enrichment._get_client")
def test_enrich_event_merges_llm_output_with_input(mock_client):
    mock_client.return_value.chat.completions.create.return_value = _mock_chat_response({
        "category": "Music",
        "tags": ["outdoor", "21+"],
        "vibe_tags": ["chill", "intimate"],
    })

    result = enrich_event(RAW_EVENT)

    assert result["id"] == RAW_EVENT["id"]
    assert result["title"] == RAW_EVENT["title"]
    assert result["price_min"] == 15.0
    assert result["category"] == "Music"
    assert result["tags"] == ["outdoor", "21+"]
    assert result["vibe_tags"] == ["chill", "intimate"]


@patch("ingestion.enrichment._get_client")
def test_enrich_event_handles_malformed_json(mock_client):
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = "not json at all"
    mock_client.return_value.chat.completions.create.return_value = response

    result = enrich_event(RAW_EVENT)

    assert result["category"] == "Other"
    assert result["vibe_tags"] == ["social"]


@patch("ingestion.enrichment._get_client")
def test_enrich_events_continues_on_per_event_failure(mock_client):
    mock_client.return_value.chat.completions.create.side_effect = [
        _mock_chat_response({"category": "Music", "tags": [], "vibe_tags": ["chill"]}),
        Exception("OpenAI rate limit"),
        _mock_chat_response({"category": "Comedy", "tags": [], "vibe_tags": ["social"]}),
    ]

    events = [
        {"id": "a", "title": "One", "description": "", "venue_name": ""},
        {"id": "b", "title": "Two", "description": "", "venue_name": ""},
        {"id": "c", "title": "Three", "description": "", "venue_name": ""},
    ]
    result = enrich_events(events)

    assert len(result) == 2
    assert [e["id"] for e in result] == ["a", "c"]
    assert result[0]["category"] == "Music"
    assert result[1]["category"] == "Comedy"
