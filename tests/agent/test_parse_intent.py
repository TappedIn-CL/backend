"""Tests for parse_intent's new time_intent / confidence / happening_now outputs.

The LLM client and embed_query are mocked so these run offline and deterministic.
"""

import json
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from agent.nodes import parse_intent


def _mock_chat_client(content: dict) -> MagicMock:
    """Build a stand-in for the AsyncOpenAI client whose chat completion
    returns `content` as a JSON string."""
    resp = MagicMock()
    message = MagicMock()
    message.content = json.dumps(content)
    choice = MagicMock()
    choice.message = message
    resp.choices = [choice]

    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=resp)
    return client


_BASE = {"query": "events happening right now near me", "chips": []}


@pytest.mark.anyio
@patch("agent.nodes.embed_query", return_value=[0.0] * 1536)
async def test_parse_intent_extracts_time_intent_and_confidence(mock_embed):
    client = _mock_chat_client(
        {"semantic_query": "events now", "filters": {}, "time_intent": "now", "confidence": 0.9}
    )
    with patch("agent.nodes._get_chat_client", return_value=client):
        result = await parse_intent(_BASE)
    assert result["time_intent"] == "now"
    assert result["confidence"] == pytest.approx(0.9)
    assert result["happening_now"] is True


@pytest.mark.anyio
@patch("agent.nodes.embed_query", return_value=[0.0] * 1536)
async def test_parse_intent_happening_now_false_for_non_now_intent(mock_embed):
    client = _mock_chat_client(
        {"semantic_query": "weekend events", "filters": {}, "time_intent": "this_weekend", "confidence": 0.8}
    )
    with patch("agent.nodes._get_chat_client", return_value=client):
        result = await parse_intent(_BASE)
    assert result["time_intent"] == "this_weekend"
    assert result["happening_now"] is False


@pytest.mark.anyio
@patch("agent.nodes.embed_query", return_value=[0.0] * 1536)
async def test_parse_intent_coerces_unknown_time_intent_to_none(mock_embed):
    client = _mock_chat_client(
        {"semantic_query": "x", "filters": {}, "time_intent": "next_decade", "confidence": 0.5}
    )
    with patch("agent.nodes._get_chat_client", return_value=client):
        result = await parse_intent(_BASE)
    assert result["time_intent"] is None
    assert result["happening_now"] is False


@pytest.mark.anyio
@patch("agent.nodes.embed_query", return_value=[0.0] * 1536)
async def test_parse_intent_clamps_out_of_range_confidence(mock_embed):
    client = _mock_chat_client(
        {"semantic_query": "x", "filters": {}, "time_intent": None, "confidence": 1.7}
    )
    with patch("agent.nodes._get_chat_client", return_value=client):
        result = await parse_intent(_BASE)
    assert result["confidence"] == 1.0


@pytest.mark.anyio
@patch("agent.nodes.embed_query", return_value=[0.0] * 1536)
async def test_parse_intent_missing_confidence_is_none(mock_embed):
    client = _mock_chat_client(
        {"semantic_query": "x", "filters": {}, "time_intent": "today"}
    )
    with patch("agent.nodes._get_chat_client", return_value=client):
        result = await parse_intent(_BASE)
    assert result["confidence"] is None
    assert result["time_intent"] == "today"


@pytest.mark.anyio
@patch("agent.nodes.embed_query", return_value=[0.0] * 1536)
async def test_parse_intent_non_string_time_intent_does_not_break_extraction(mock_embed):
    # A malformed (non-string) time_intent must be coerced to None WITHOUT
    # discarding the rest of a successful extraction.
    client = _mock_chat_client(
        {"semantic_query": "rooftop party", "filters": {}, "time_intent": ["now"], "confidence": 0.8}
    )
    with patch("agent.nodes._get_chat_client", return_value=client):
        result = await parse_intent(_BASE)
    assert result["time_intent"] is None
    assert result["semantic_query"] == "rooftop party"
    assert result["confidence"] == pytest.approx(0.8)


@pytest.mark.anyio
@patch("agent.nodes.embed_query", return_value=[0.0] * 1536)
async def test_parse_intent_llm_failure_sets_safe_defaults(mock_embed):
    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=RuntimeError("boom"))
    with patch("agent.nodes._get_chat_client", return_value=client):
        result = await parse_intent(_BASE)
    # On total LLM failure, confidence is 0.0 to signal the future clarify node.
    assert result["time_intent"] is None
    assert result["confidence"] == 0.0
    assert result["happening_now"] is False
    # Existing fallback behaviour is preserved.
    assert result["semantic_query"] == _BASE["query"]
