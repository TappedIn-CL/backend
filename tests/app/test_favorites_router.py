"""Tests for /users/me/favorites endpoints.

The favorites tables use Postgres-only column types (UUID, ARRAY), so an
in-memory SQLite session won't bind cleanly. Instead, we override the
`get_db` dependency with a MagicMock session and script the .query() chain
on a per-test basis.
"""
from datetime import datetime, timedelta
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.models.event import Event
from app.models.favorite import UserFavorite
from auth.deps import (
    get_bearer_token,
    get_jwt_payload,
    get_optional_jwt_payload,
    get_supabase_sub,
)
from db.dependencies import get_db


# ── fixtures ───────────────────────────────────────────────────────────────

USER_ID = str(uuid4())


@pytest.fixture
def db_mock():
    return MagicMock(name="Session")


@pytest.fixture
def client(db_mock):
    app.dependency_overrides[get_db] = lambda: db_mock
    app.dependency_overrides[get_supabase_sub] = lambda: USER_ID
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def unauth_client(db_mock):
    """Client without auth override → real auth dep runs and 401s."""
    app.dependency_overrides[get_db] = lambda: db_mock
    yield TestClient(app)
    app.dependency_overrides.clear()


def _fake_event(event_id: UUID, title: str = "Sample Event") -> Event:
    """SQLAlchemy ORM instances built without touching the DB."""
    return Event(
        id=event_id,
        title=title,
        description="desc",
        date=datetime.utcnow() + timedelta(days=1),
        cost=10.0,
        location="Venue X",
        category="Music",
        special_tags="outdoor",
        vibe_tags="chill",
        source="test",
        source_id=str(event_id),
        is_active=True,
        created_at=datetime.utcnow(),
    )


def _fake_favorite(user_id: str, event_id: UUID) -> UserFavorite:
    return UserFavorite(
        user_id=UUID(user_id),
        event_id=event_id,
        created_at=datetime.utcnow(),
    )


def _script_query_chain(db_mock, model_to_result: dict):
    """Build a side_effect for db.query() that returns a model-specific
    chain. `model_to_result` maps model class → final .first()/.all() value
    (use a tuple for staged results across .first() calls)."""
    chains = {}

    def make_chain(result):
        chain = MagicMock()
        chain.filter.return_value = chain
        chain.join.return_value = chain
        chain.order_by.return_value = chain
        chain.limit.return_value = chain
        chain.first.return_value = result
        chain.all.return_value = result if isinstance(result, list) else [result] if result else []
        return chain

    for model, result in model_to_result.items():
        chains[model] = make_chain(result)

    def query_side_effect(model):
        return chains.get(model, MagicMock())

    db_mock.query.side_effect = query_side_effect
    return chains


# ── POST /users/me/favorites ───────────────────────────────────────────────

def test_post_favorite_creates_new_row_returns_201(client, db_mock):
    event_id = uuid4()
    event = _fake_event(event_id)

    # Event lookup returns event; favorite lookup returns None (not existing)
    event_chain = MagicMock()
    event_chain.filter.return_value.first.return_value = event
    fav_chain = MagicMock()
    fav_chain.filter.return_value.first.return_value = None

    def query_side(model):
        return {Event: event_chain, UserFavorite: fav_chain}[model]
    db_mock.query.side_effect = query_side

    # On commit/refresh, the favorite is assigned a created_at
    def refresh(obj):
        obj.created_at = datetime.utcnow()
    db_mock.refresh.side_effect = refresh

    resp = client.post("/users/me/favorites", json={"event_id": str(event_id)})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["event_id"] == str(event_id)
    assert "created_at" in body
    db_mock.add.assert_called_once()
    db_mock.commit.assert_called_once()


def test_post_favorite_duplicate_returns_existing_201_idempotent(client, db_mock):
    event_id = uuid4()
    event = _fake_event(event_id)
    existing = _fake_favorite(USER_ID, event_id)

    event_chain = MagicMock()
    event_chain.filter.return_value.first.return_value = event
    fav_chain = MagicMock()
    fav_chain.filter.return_value.first.return_value = existing

    def query_side(model):
        return {Event: event_chain, UserFavorite: fav_chain}[model]
    db_mock.query.side_effect = query_side

    resp = client.post("/users/me/favorites", json={"event_id": str(event_id)})
    assert resp.status_code == 201
    body = resp.json()
    assert body["event_id"] == str(event_id)
    db_mock.add.assert_not_called()
    db_mock.commit.assert_not_called()


def test_post_favorite_nonexistent_event_returns_404(client, db_mock):
    event_chain = MagicMock()
    event_chain.filter.return_value.first.return_value = None

    def query_side(model):
        if model is Event:
            return event_chain
        return MagicMock()
    db_mock.query.side_effect = query_side

    resp = client.post("/users/me/favorites", json={"event_id": str(uuid4())})
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Event not found"


def test_post_favorite_without_auth_returns_401(unauth_client):
    resp = unauth_client.post(
        "/users/me/favorites", json={"event_id": str(uuid4())}
    )
    assert resp.status_code == 401


def test_post_favorite_invalid_uuid_returns_422(client):
    resp = client.post("/users/me/favorites", json={"event_id": "not-a-uuid"})
    assert resp.status_code == 422


# ── DELETE /users/me/favorites/{event_id} ──────────────────────────────────

def test_delete_existing_favorite_returns_204(client, db_mock):
    event_id = uuid4()
    fav = _fake_favorite(USER_ID, event_id)

    fav_chain = MagicMock()
    fav_chain.filter.return_value.first.return_value = fav

    def query_side(model):
        if model is UserFavorite:
            return fav_chain
        return MagicMock()
    db_mock.query.side_effect = query_side

    resp = client.delete(f"/users/me/favorites/{event_id}")
    assert resp.status_code == 204
    db_mock.delete.assert_called_once_with(fav)
    db_mock.commit.assert_called_once()


def test_delete_non_favorited_returns_404(client, db_mock):
    fav_chain = MagicMock()
    fav_chain.filter.return_value.first.return_value = None

    def query_side(model):
        if model is UserFavorite:
            return fav_chain
        return MagicMock()
    db_mock.query.side_effect = query_side

    resp = client.delete(f"/users/me/favorites/{uuid4()}")
    assert resp.status_code == 404
    db_mock.delete.assert_not_called()


def test_delete_without_auth_returns_401(unauth_client):
    resp = unauth_client.delete(f"/users/me/favorites/{uuid4()}")
    assert resp.status_code == 401


def test_delete_invalid_uuid_returns_422(client):
    resp = client.delete("/users/me/favorites/not-a-uuid")
    assert resp.status_code == 422


# ── GET /users/me/favorites ────────────────────────────────────────────────

def test_get_favorites_returns_newest_first_hydrated_list(client, db_mock):
    e1 = _fake_event(uuid4(), title="Newer")
    e2 = _fake_event(uuid4(), title="Older")

    chain = MagicMock()
    chain.join.return_value = chain
    chain.filter.return_value = chain
    chain.order_by.return_value = chain
    chain.all.return_value = [e1, e2]  # Newer first (router DESC order)
    db_mock.query.return_value = chain

    resp = client.get("/users/me/favorites")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == 2
    assert body[0]["title"] == "Newer"
    assert body[1]["title"] == "Older"
    # Verify order_by was actually invoked (newest-first contract).
    chain.order_by.assert_called_once()


def test_get_favorites_empty_returns_empty_list(client, db_mock):
    chain = MagicMock()
    chain.join.return_value = chain
    chain.filter.return_value = chain
    chain.order_by.return_value = chain
    chain.all.return_value = []
    db_mock.query.return_value = chain

    resp = client.get("/users/me/favorites")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_favorites_without_auth_returns_401(unauth_client):
    resp = unauth_client.get("/users/me/favorites")
    assert resp.status_code == 401
