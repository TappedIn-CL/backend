"""Tests for agent/recommendations.py::recommend_for_you and helpers.

The pipeline is fully mocked: Pinecone (search_events, fetch_vectors),
DB hydration (_hydrate_from_db, _fetch_recent_events), and event_to_hydrated
where needed. We never construct real Event ORM rows because the Postgres
ARRAY/UUID columns aren't SQLite-portable.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from agent import recommendations as recs
from agent.recommendations import (
    _build_pinecone_filter,
    _to_event_schema,
    recommend_for_you,
)


# ── helpers ────────────────────────────────────────────────────────────────

def _evt(id_str: str | None = None, title: str = "T", **over) -> dict:
    base = {
        "id": id_str or str(uuid4()),
        "title": title,
        "description": "",
        "category": "Music",
        "tags": [],
        "vibe_tags": [],
        "venue_name": "",
        "address": "",
        "city": "Los Angeles",
        "latitude": 0.0,
        "longitude": 0.0,
        "price_min": 0.0,
        "price_max": 0.0,
        "start_time": "2026-05-10T19:00:00Z",
        "end_time": None,
        "image_url": None,
        "source_url": "",
    }
    base.update(over)
    return base


def _hydrated_obj(id_str: str, title: str = "T") -> SimpleNamespace:
    """Mock HydratedEventResponse-ish object for _to_event_schema."""
    return SimpleNamespace(
        id=id_str,
        title=title,
        description="",
        category="Music",
        tags=[],
        vibe_tags=[],
        venue_name="",
        address="",
        city="Los Angeles",
        latitude=0.0,
        longitude=0.0,
        price_min=0.0,
        price_max=0.0,
        start_time="2026-05-10T19:00:00Z",
        end_time=None,
        image_url=None,
        source_url="",
    )


# ── _build_pinecone_filter ─────────────────────────────────────────────────

def test_build_pinecone_filter_with_price_max():
    assert _build_pinecone_filter({"price_max": 25.0}) == {
        "price_max": {"$lte": 25.0}
    }


def test_build_pinecone_filter_no_price_max_returns_empty():
    assert _build_pinecone_filter({}) == {}
    assert _build_pinecone_filter({"price_max": None}) == {}


def test_build_pinecone_filter_zero_price_is_kept():
    # Free events shouldn't be silently filtered away — 0.0 is a real bound.
    assert _build_pinecone_filter({"price_max": 0.0}) == {
        "price_max": {"$lte": 0.0}
    }


def test_build_pinecone_filter_coerces_to_float():
    out = _build_pinecone_filter({"price_max": 20})
    assert out == {"price_max": {"$lte": 20.0}}
    assert isinstance(out["price_max"]["$lte"], float)


# ── _to_event_schema ───────────────────────────────────────────────────────

def test_to_event_schema_copies_all_fields():
    h = _hydrated_obj("abc", "Hello")
    out = _to_event_schema(h)
    assert out["id"] == "abc"
    assert out["title"] == "Hello"
    assert out["city"] == "Los Angeles"


# ── recommend_for_you: cold-start branch ───────────────────────────────────

EMPTY_PROFILE = {
    "interests": [],
    "vibes": [],
    "favorited_tags": [],
    "favorited_event_ids": [],
    "price_max": None,
    "neighborhood": None,
}


@pytest.mark.anyio
async def test_cold_start_uses_recency_fallback_not_pinecone():
    db = MagicMock()
    recent_rows = [MagicMock(name="row1"), MagicMock(name="row2")]

    with patch.object(recs, "_fetch_recent_events", return_value=recent_rows) as mock_recent, \
         patch.object(recs, "event_to_hydrated",
                      side_effect=lambda r: _hydrated_obj("id-" + str(id(r)))), \
         patch.object(recs, "search_events") as mock_search, \
         patch.object(recs, "fetch_vectors") as mock_fetch:
        result = await recommend_for_you(EMPTY_PROFILE, db, limit=5)

    mock_search.assert_not_called()
    mock_fetch.assert_not_called()
    mock_recent.assert_called_once()
    assert len(result) == 2


@pytest.mark.anyio
async def test_cold_start_passes_favorite_ids_to_exclude_set():
    db = MagicMock()
    fav_id = str(uuid4())
    profile = {**EMPTY_PROFILE, "favorited_event_ids": [fav_id]}

    captured = {}

    def fake_fetch_recent(db_arg, limit, exclude_ids):
        captured["exclude_ids"] = exclude_ids
        return []

    with patch.object(recs, "_fetch_recent_events", side_effect=fake_fetch_recent), \
         patch.object(recs, "event_to_hydrated"):
        await recommend_for_you(profile, db, limit=10)
    assert fav_id in captured["exclude_ids"]


@pytest.mark.anyio
async def test_cold_start_respects_limit_param():
    db = MagicMock()
    captured = {}

    def fake_fetch_recent(db_arg, limit, exclude_ids):
        captured["limit"] = limit
        return []

    with patch.object(recs, "_fetch_recent_events", side_effect=fake_fetch_recent):
        await recommend_for_you(EMPTY_PROFILE, db, limit=7)
    assert captured["limit"] == 7


def test_fetch_recent_events_filters_active_future_and_excludes():
    """Verify the recency-fallback DB query composition: active=True,
    date>=now, exclude favorites, ordered ascending, .limit() applied."""
    db = MagicMock()
    query_chain = db.query.return_value
    # Each .filter() / .order_by() returns the same chain object
    query_chain.filter.return_value = query_chain
    query_chain.order_by.return_value = query_chain
    query_chain.limit.return_value.all.return_value = ["e1", "e2"]

    out = recs._fetch_recent_events(db, limit=5, exclude_ids={str(uuid4())})
    assert out == ["e1", "e2"]
    # At least 2 filter calls (date + is_active), plus exclude_ids
    assert query_chain.filter.call_count >= 3
    query_chain.order_by.assert_called_once()
    query_chain.limit.assert_called_once_with(5)


def test_fetch_recent_events_invalid_uuid_in_excludes_is_tolerated():
    """Non-UUID strings in exclude_ids must not break the query."""
    db = MagicMock()
    chain = db.query.return_value
    chain.filter.return_value = chain
    chain.order_by.return_value = chain
    chain.limit.return_value.all.return_value = []
    # Should not raise.
    recs._fetch_recent_events(db, limit=5, exclude_ids={"not-a-uuid"})


# ── recommend_for_you: happy path ─────────────────────────────────────────

@pytest.mark.anyio
async def test_happy_path_builds_taste_searches_pinecone_and_ranks():
    """End-to-end: taste vector computed → search_events called → hydration →
    ranking by cosine(taste, event_vec) → top-K returned."""
    db = MagicMock()
    profile = {
        "interests": ["jazz"],
        "vibes": [],
        "favorited_tags": [],
        "favorited_event_ids": [],
        "price_max": 25.0,
        "neighborhood": None,
    }

    e1, e2 = str(uuid4()), str(uuid4())
    matches = [
        {"id": e1, "metadata": {"title": "Jazz Night"}},
        {"id": e2, "metadata": {"title": "Rooftop Set"}},
    ]
    captured = {}

    def fake_search(vec, flt, top_k):
        captured["vec"] = vec
        captured["filter"] = flt
        captured["top_k"] = top_k
        return matches

    # e2 vector aligns with taste (taste = [1,0,0] for this test)
    def fake_fetch_vectors(ids):
        return {e1: [0.0, 1.0, 0.0], e2: [1.0, 0.0, 0.0]}

    def fake_hydrate(db_arg, ids):
        return [_to_event_schema(_hydrated_obj(i, title="Jazz Night" if i == e1 else "Rooftop Set"))
                for i in ids]

    with patch.object(recs, "search_events", side_effect=fake_search), \
         patch.object(recs, "fetch_vectors", side_effect=fake_fetch_vectors), \
         patch.object(recs, "_hydrate_from_db", side_effect=fake_hydrate), \
         patch("agent.scoring.embed_text", return_value=[1.0, 0.0, 0.0]):
        result = await recommend_for_you(profile, db, limit=5)

    assert captured["filter"] == {"price_max": {"$lte": 25.0}}
    assert captured["top_k"] >= 5  # overfetch factor applied
    # Ranking: e2 should rank above e1 because its vector aligns with taste.
    assert [r["id"] for r in result] == [e2, e1]
    assert "score" in result[0]
    assert result[0]["score"] > result[1]["score"]


@pytest.mark.anyio
async def test_excludes_favorited_event_ids_from_pinecone_matches():
    db = MagicMock()
    fav = str(uuid4())
    keep = str(uuid4())
    profile = {**EMPTY_PROFILE, "interests": ["x"], "favorited_event_ids": [fav]}

    matches = [
        {"id": fav, "metadata": {"title": "Should Be Skipped"}},
        {"id": keep, "metadata": {"title": "Keep Me"}},
    ]

    seen_hydrate_ids = {}

    def fake_hydrate(db_arg, ids):
        seen_hydrate_ids["ids"] = ids
        return [_to_event_schema(_hydrated_obj(i, "T-" + i)) for i in ids]

    with patch.object(recs, "search_events", return_value=matches), \
         patch.object(recs, "fetch_vectors", return_value={keep: [1.0, 0.0]}), \
         patch.object(recs, "_hydrate_from_db", side_effect=fake_hydrate), \
         patch("agent.scoring.embed_text", return_value=[1.0, 0.0]):
        result = await recommend_for_you(profile, db, limit=5)

    assert fav not in seen_hydrate_ids["ids"]
    assert keep in seen_hydrate_ids["ids"]
    assert all(r["id"] != fav for r in result)


@pytest.mark.anyio
async def test_title_dedup_keeps_first_match_only():
    db = MagicMock()
    id1, id2, id3 = str(uuid4()), str(uuid4()), str(uuid4())
    matches = [
        {"id": id1, "metadata": {"title": "Sunset Yoga"}},
        {"id": id2, "metadata": {"title": "SUNSET YOGA"}},   # case-insensitive dup
        {"id": id3, "metadata": {"title": "Different Title"}},
    ]
    seen = {}

    def fake_hydrate(db_arg, ids):
        seen["ids"] = ids
        return [_to_event_schema(_hydrated_obj(i)) for i in ids]

    with patch.object(recs, "search_events", return_value=matches), \
         patch.object(recs, "fetch_vectors",
                      return_value={id1: [1.0, 0.0], id3: [1.0, 0.0]}), \
         patch.object(recs, "_hydrate_from_db", side_effect=fake_hydrate), \
         patch("agent.scoring.embed_text", return_value=[1.0, 0.0]):
        await recommend_for_you({**EMPTY_PROFILE, "interests": ["x"]}, db, limit=5)

    assert id1 in seen["ids"]
    assert id2 not in seen["ids"]
    assert id3 in seen["ids"]


@pytest.mark.anyio
async def test_title_dedup_skips_blank_titles():
    db = MagicMock()
    id1, id2 = str(uuid4()), str(uuid4())
    matches = [
        {"id": id1, "metadata": {"title": "   "}},
        {"id": id2, "metadata": {"title": "Real"}},
    ]
    seen = {}

    def fake_hydrate(db_arg, ids):
        seen["ids"] = ids
        return [_to_event_schema(_hydrated_obj(i)) for i in ids]

    with patch.object(recs, "search_events", return_value=matches), \
         patch.object(recs, "fetch_vectors", return_value={id2: [1.0]}), \
         patch.object(recs, "_hydrate_from_db", side_effect=fake_hydrate), \
         patch("agent.scoring.embed_text", return_value=[1.0]):
        await recommend_for_you({**EMPTY_PROFILE, "interests": ["x"]}, db, limit=5)
    assert id1 not in seen["ids"]
    assert id2 in seen["ids"]


@pytest.mark.anyio
async def test_pinecone_search_failure_falls_back_to_recency():
    db = MagicMock()
    rows = [MagicMock()]

    with patch.object(recs, "search_events",
                      side_effect=RuntimeError("pinecone 500")), \
         patch.object(recs, "_fetch_recent_events", return_value=rows) as mock_recent, \
         patch.object(recs, "event_to_hydrated",
                      side_effect=lambda r: _hydrated_obj("fallback")), \
         patch("agent.scoring.embed_text", return_value=[1.0, 0.0]):
        result = await recommend_for_you(
            {**EMPTY_PROFILE, "interests": ["x"]}, db, limit=3
        )
    mock_recent.assert_called_once()
    assert len(result) == 1


@pytest.mark.anyio
async def test_vector_fetch_failure_during_ranking_preserves_pinecone_order():
    db = MagicMock()
    id1, id2 = str(uuid4()), str(uuid4())
    matches = [
        {"id": id1, "metadata": {"title": "First"}},
        {"id": id2, "metadata": {"title": "Second"}},
    ]

    def fake_hydrate(db_arg, ids):
        return [_to_event_schema(_hydrated_obj(i, "T-" + i)) for i in ids]

    with patch.object(recs, "search_events", return_value=matches), \
         patch.object(recs, "fetch_vectors", side_effect=RuntimeError("boom")), \
         patch.object(recs, "_hydrate_from_db", side_effect=fake_hydrate), \
         patch("agent.scoring.embed_text", return_value=[1.0, 0.0]):
        result = await recommend_for_you(
            {**EMPTY_PROFILE, "interests": ["x"]}, db, limit=5
        )
    # Order preserved from search_events order
    assert [r["id"] for r in result] == [id1, id2]


@pytest.mark.anyio
async def test_limit_clamps_returned_events():
    db = MagicMock()
    ids = [str(uuid4()) for _ in range(6)]
    matches = [
        {"id": i, "metadata": {"title": f"T{n}"}} for n, i in enumerate(ids)
    ]

    def fake_hydrate(db_arg, ids_in):
        return [_to_event_schema(_hydrated_obj(i, f"H-{i}")) for i in ids_in]

    vec_map = {i: [1.0, 0.0] for i in ids}
    with patch.object(recs, "search_events", return_value=matches), \
         patch.object(recs, "fetch_vectors", return_value=vec_map), \
         patch.object(recs, "_hydrate_from_db", side_effect=fake_hydrate), \
         patch("agent.scoring.embed_text", return_value=[1.0, 0.0]):
        result = await recommend_for_you(
            {**EMPTY_PROFILE, "interests": ["x"]}, db, limit=3
        )
    assert len(result) == 3


@pytest.mark.anyio
async def test_empty_pinecone_matches_returns_empty_list():
    db = MagicMock()
    with patch.object(recs, "search_events", return_value=[]), \
         patch.object(recs, "_hydrate_from_db") as mock_hydrate, \
         patch("agent.scoring.embed_text", return_value=[1.0, 0.0]):
        result = await recommend_for_you(
            {**EMPTY_PROFILE, "interests": ["x"]}, db, limit=5
        )
    assert result == []
    mock_hydrate.assert_not_called()
