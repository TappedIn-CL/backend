"""User profile loading for personalization.

Builds the user_profile dict consumed by the agent's compute_taste node and
the For You recommendation pipeline. Centralizes JWT → DB → profile dict so
both /agent/query and /agent/for-you share the same enrichment logic.
"""
import logging
import re
from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.models.favorite import UserFavorite
from app.models.user import User
from auth.deps import get_jwt_payload, get_optional_jwt_payload
from db.dependencies import get_db

logger = logging.getLogger(__name__)


def _parse_price_max(price_range: str | None) -> float | None:
    """Best-effort parse of price_range strings into a numeric upper bound.

    Tolerant by design — the column is free-form ("Free", "$0-$20",
    "Under 50", "$$$"). Returns None when no upper bound is extractable so
    downstream Pinecone filter logic can skip the constraint cleanly rather
    than over-filtering on a misparse.
    """
    if not price_range:
        return None
    s = price_range.strip().lower()
    if s in {"free", "$0", "0"}:
        return 0.0
    # Pull every number; the largest is the upper bound.
    numbers = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", s)]
    if not numbers:
        return None
    return max(numbers)


def _build_profile(user: User, favorited_event_ids: list[str]) -> dict:
    return {
        "interests": user.interests or [],
        "vibes": user.vibes or [],
        "favorited_tags": [],
        "favorited_event_ids": favorited_event_ids,
        "price_max": _parse_price_max(user.price_range),
        "neighborhood": user.neighborhood,
    }


def _load_profile_for_sub(db: Session, user_id: str) -> dict | None:
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        return None
    fav_rows = (
        db.query(UserFavorite.event_id)
        .filter(UserFavorite.user_id == user_id)
        .all()
    )
    favorited_event_ids = [str(row[0]) for row in fav_rows]
    return _build_profile(user, favorited_event_ids)


def get_user_profile_optional(
    payload: Annotated[dict | None, Depends(get_optional_jwt_payload)],
    db: Annotated[Session, Depends(get_db)],
) -> dict | None:
    """Anonymous-allowed: returns None for unauthenticated callers.

    Used by /agent/query, which serves both signed-in and anonymous users.
    """
    if not payload:
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    return _load_profile_for_sub(db, user_id)


def get_user_profile_required(
    payload: Annotated[dict, Depends(get_jwt_payload)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Auth-required: 401 if no/invalid JWT, 404 if user row is missing.

    Used by /agent/for-you which is meaningless without a profile.
    """
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token subject")
    profile = _load_profile_for_sub(db, user_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="User profile not found")
    return profile
