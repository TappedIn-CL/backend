"""Tests for agent/popular.py::popular_events and helpers."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from agent import popular as pop
from agent.popular import popular_events


def _hydrated_obj(id_str: str, title: str = "T") -> SimpleNamespace:
    return SimpleNamespace(
        id=id_str,
        title=title,
        description="",
        category="Music",
        tags=[],
        vibe_tags=[],
        venue_name="Venue",
        address="LA",
        city="Los Angeles",
        latitude=None,
        longitude=None,
        price_min=0.0,
        price_max=0.0,
        start_time="2026-06-10T19:00:00Z",
        end_time=None,
        image_url=None,
        source_url=None,
        score=None,
    )


def _mock_event(title: str = "Event") -> MagicMock:
    ev = MagicMock()
    ev.id = uuid4()
    ev.title = title
    return ev


@pytest.mark.anyio
async def test_popular_events_returns_scored_by_save_count():
    hot = _mock_event("Hot")
    warm = _mock_event("Warm")
    db = MagicMock()

    with patch.object(pop, "_fetch_popular_events", return_value=[(hot, 10), (warm, 5)]), \
         patch.object(pop, "event_to_hydrated", side_effect=lambda e: _hydrated_obj(str(e.id), e.title)):
        result = await popular_events(db, limit=5)

    assert len(result) == 2
    assert result[0]["score"] == 1.0
    assert result[1]["score"] == 0.5


@pytest.mark.anyio
async def test_popular_events_recency_fallback_when_no_saves():
    db = MagicMock()
    fallback_event = _mock_event("Soon")

    with patch.object(pop, "_fetch_popular_events", return_value=[]), \
         patch.object(pop, "_fetch_recent_events", return_value=[fallback_event]), \
         patch.object(pop, "event_to_hydrated", return_value=_hydrated_obj("x", "Soon")):
        result = await popular_events(db, limit=5)

    assert len(result) == 1
    assert result[0]["title"] == "Soon"
    assert "score" not in result[0]


@pytest.mark.anyio
async def test_popular_events_empty_when_no_saves_and_no_upcoming():
    db = MagicMock()

    with patch.object(pop, "_fetch_popular_events", return_value=[]), \
         patch.object(pop, "_fetch_recent_events", return_value=[]):
        result = await popular_events(db, limit=5)

    assert result == []


def test_to_scored_schemas_normalizes_against_max():
    e1, e2 = _mock_event("A"), _mock_event("B")
    with patch.object(pop, "event_to_hydrated", side_effect=lambda e: _hydrated_obj(str(e.id), e.title)):
        out = pop._to_scored_schemas([(e1, 4), (e2, 1)])

    assert out[0]["score"] == 1.0
    assert out[1]["score"] == 0.25
