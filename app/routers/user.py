import logging
import uuid
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models.event import Event
from app.models.favorite import UserFavorite
from app.models.friendship import Friendship
from app.models.going_to import UserGoingTo
from app.models.google_credentials import GoogleCredentials
from app.models.user import User
from app.services import google_calendar
from app.services.google_calendar import CalendarSyncError
from app.utils.event_utils import event_to_hydrated
from auth.deps import get_jwt_payload, get_supabase_sub
from db.dependencies import get_db
from schemas.event import HydratedEventResponse
from schemas.user import (
    CalendarSync,
    FavoriteCreate,
    FavoriteResponse,
    GoingToCreate,
    GoingToDeleteResponse,
    GoingToPostResponse,
    GoingToResponse,
    UserUpdate,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _favorite_ids(db: Session, user_id: uuid.UUID) -> list[str]:
    rows = (
        db.query(UserFavorite.event_id)
        .filter(UserFavorite.user_id == user_id)
        .all()
    )
    return [str(row[0]) for row in rows]


def _going_to_ids(db: Session, user_id: uuid.UUID) -> list[str]:
    rows = (
        db.query(UserGoingTo.event_id)
        .filter(UserGoingTo.user_id == user_id)
        .all()
    )
    return [str(row[0]) for row in rows]


def _gcal_connected(db: Session, user_id: uuid.UUID) -> bool:
    return (
        db.query(GoogleCredentials.user_id)
        .filter(GoogleCredentials.user_id == user_id)
        .first()
        is not None
    )


def _user_to_dict(user: User, db: Session) -> dict:
    return {
        "id": str(user.id),
        "email": user.email,
        "username": user.username,
        "full_name": user.full_name,
        "phone_number": user.phone_number,
        "avatar_url": user.avatar_url,
        "vibes": user.vibes,
        "search_radius": user.search_radius,
        "price_range": user.price_range,
        "preferred_days": user.preferred_days,
        "email_notifs": user.email_notifs,
        "push_notifs": user.push_notifs,
        "sms_notifs": user.sms_notifs,
        "date_of_birth": user.date_of_birth,
        "pronouns": user.pronouns,
        "gender": user.gender,
        "neighborhood": user.neighborhood,
        "occupation": user.occupation,
        "interests": user.interests,
        "favorite_events": _favorite_ids(db, user.id),
        "going_to_events": _going_to_ids(db, user.id),
        "google_calendar_connected": _gcal_connected(db, user.id),
    }


def _public_user_dict(user: User) -> dict:
    return {
        "id": str(user.id),
        "username": user.username,
        "avatar_url": user.avatar_url,
    }


def _get_or_create_user(payload: dict, db: Session) -> User:
    user_id = payload.get("sub")
    email = payload.get("email", "")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        user = User(id=uuid.UUID(user_id), email=email)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def _are_friends(db: Session, user_a: uuid.UUID, user_b: uuid.UUID) -> bool:
    return (
        db.query(Friendship)
        .filter(
            Friendship.status == "accepted",
            or_(
                and_(Friendship.requester_id == user_a, Friendship.addressee_id == user_b),
                and_(Friendship.requester_id == user_b, Friendship.addressee_id == user_a),
            ),
        )
        .first()
        is not None
    )


# ─── /me ──────────────────────────────────────────────────────────────────────

@router.get("/me")
def read_me(
    payload: Annotated[dict, Depends(get_jwt_payload)],
    db: Annotated[Session, Depends(get_db)],
):
    user = _get_or_create_user(payload, db)
    return _user_to_dict(user, db)


@router.patch("/me")
def patch_me(
    body: UserUpdate,
    payload: Annotated[dict, Depends(get_jwt_payload)],
    db: Annotated[Session, Depends(get_db)],
):
    user = _get_or_create_user(payload, db)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return _user_to_dict(user, db)


# ─── Favorites (user_favorites junction table) ─────────────────────────────

@router.post(
    "/me/favorites",
    response_model=FavoriteResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_favorite(
    payload: FavoriteCreate,
    user_id: Annotated[str, Depends(get_supabase_sub)],
    db: Annotated[Session, Depends(get_db)],
) -> FavoriteResponse:
    event = db.query(Event).filter(Event.id == payload.event_id).first()
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")

    existing = (
        db.query(UserFavorite)
        .filter(
            UserFavorite.user_id == user_id,
            UserFavorite.event_id == payload.event_id,
        )
        .first()
    )
    if existing is not None:
        return existing

    fav = UserFavorite(user_id=user_id, event_id=payload.event_id)
    db.add(fav)
    db.commit()
    db.refresh(fav)
    return fav


@router.delete("/me/favorites/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_favorite(
    event_id: UUID,
    user_id: Annotated[str, Depends(get_supabase_sub)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    fav = (
        db.query(UserFavorite)
        .filter(
            UserFavorite.user_id == user_id,
            UserFavorite.event_id == event_id,
        )
        .first()
    )
    if fav is None:
        raise HTTPException(status_code=404, detail="Favorite not found")
    db.delete(fav)
    db.commit()


@router.get("/me/favorites", response_model=list[HydratedEventResponse])
def list_favorites(
    user_id: Annotated[str, Depends(get_supabase_sub)],
    db: Annotated[Session, Depends(get_db)],
) -> list[HydratedEventResponse]:
    rows = (
        db.query(Event)
        .join(UserFavorite, UserFavorite.event_id == Event.id)
        .filter(UserFavorite.user_id == user_id)
        .order_by(UserFavorite.created_at.desc())
        .all()
    )
    return [event_to_hydrated(e) for e in rows]


# ─── Going To ─────────────────────────────────────────────────────────────────


def _try_calendar_insert(user_id: str, db: Session, event: Event) -> tuple[str | None, CalendarSync]:
    if event.date is None:
        return None, CalendarSync(ok=False, reason="missing_time")
    if event.date < datetime.utcnow():
        return None, CalendarSync(ok=False, reason="past_event")
    try:
        gcal_id = google_calendar.insert_event(user_id, db, event)
        return gcal_id, CalendarSync(ok=True)
    except CalendarSyncError as e:
        return None, CalendarSync(ok=False, reason=e.reason)


def _try_calendar_delete(user_id: str, db: Session, google_event_id: str) -> CalendarSync:
    try:
        google_calendar.delete_event(user_id, db, google_event_id)
        return CalendarSync(ok=True)
    except CalendarSyncError as e:
        return CalendarSync(ok=False, reason=e.reason)


@router.post(
    "/me/going-to",
    response_model=GoingToPostResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_going_to(
    payload: GoingToCreate,
    user_id: Annotated[str, Depends(get_supabase_sub)],
    db: Annotated[Session, Depends(get_db)],
) -> GoingToPostResponse:
    event = db.query(Event).filter(Event.id == payload.event_id).first()
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")

    row = (
        db.query(UserGoingTo)
        .filter(
            UserGoingTo.user_id == user_id,
            UserGoingTo.event_id == payload.event_id,
        )
        .first()
    )
    if row is None:
        row = UserGoingTo(user_id=user_id, event_id=payload.event_id)
        db.add(row)
        db.commit()
        db.refresh(row)

    # Auto-favorite on RSVP (W6 spec). Idempotent: if the user already
    # favorited this event, do nothing. Uses the user_favorites junction
    # table — the canonical store on main, not the legacy array column.
    existing_fav = (
        db.query(UserFavorite)
        .filter(
            UserFavorite.user_id == user_id,
            UserFavorite.event_id == payload.event_id,
        )
        .first()
    )
    if existing_fav is None:
        db.add(UserFavorite(user_id=user_id, event_id=payload.event_id))
        db.commit()

    if row.google_event_id:
        sync = CalendarSync(ok=True)
    else:
        gcal_id, sync = _try_calendar_insert(user_id, db, event)
        if gcal_id is not None:
            row.google_event_id = gcal_id
            db.commit()
            db.refresh(row)

    return GoingToPostResponse(
        going_to=GoingToResponse.model_validate(row),
        calendar_sync=sync,
    )


@router.delete("/me/going-to/{event_id}", response_model=GoingToDeleteResponse)
def remove_going_to(
    event_id: UUID,
    user_id: Annotated[str, Depends(get_supabase_sub)],
    db: Annotated[Session, Depends(get_db)],
) -> GoingToDeleteResponse:
    row = (
        db.query(UserGoingTo)
        .filter(
            UserGoingTo.user_id == user_id,
            UserGoingTo.event_id == event_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Going-to entry not found")

    sync = CalendarSync(ok=True)
    if row.google_event_id:
        sync = _try_calendar_delete(user_id, db, row.google_event_id)

    db.delete(row)
    db.commit()
    return GoingToDeleteResponse(calendar_sync=sync)


@router.get("/me/going-to")
def list_going_to(
    user_id: Annotated[str, Depends(get_supabase_sub)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    rows = (
        db.query(UserGoingTo.event_id)
        .filter(UserGoingTo.user_id == user_id)
        .order_by(UserGoingTo.created_at.desc())
        .all()
    )
    return {"going_to_events": [str(r.event_id) for r in rows]}


# ─── Friends ──────────────────────────────────────────────────────────────────

@router.get("/me/friends")
def get_friends(
    payload: Annotated[dict, Depends(get_jwt_payload)],
    db: Annotated[Session, Depends(get_db)],
):
    user_id = uuid.UUID(payload.get("sub"))
    rows = db.query(Friendship).filter(
        Friendship.status == "accepted",
        or_(Friendship.requester_id == user_id, Friendship.addressee_id == user_id),
    ).all()
    friend_ids = [
        row.addressee_id if row.requester_id == user_id else row.requester_id
        for row in rows
    ]
    if not friend_ids:
        return []
    friends = db.query(User).filter(User.id.in_(friend_ids)).all()
    return [_public_user_dict(f) for f in friends]


@router.get("/me/friends/requests")
def get_friend_requests(
    payload: Annotated[dict, Depends(get_jwt_payload)],
    db: Annotated[Session, Depends(get_db)],
):
    user_id = uuid.UUID(payload.get("sub"))
    rows = db.query(Friendship).filter(
        Friendship.addressee_id == user_id,
        Friendship.status == "pending",
    ).all()
    requester_ids = [row.requester_id for row in rows]
    if not requester_ids:
        return []
    requesters = db.query(User).filter(User.id.in_(requester_ids)).all()
    return [_public_user_dict(r) for r in requesters]


@router.get("/me/friends/sent")
def get_sent_friend_requests(
    payload: Annotated[dict, Depends(get_jwt_payload)],
    db: Annotated[Session, Depends(get_db)],
):
    user_id = uuid.UUID(payload.get("sub"))
    rows = db.query(Friendship).filter(
        Friendship.requester_id == user_id,
        Friendship.status == "pending",
    ).all()
    addressee_ids = [row.addressee_id for row in rows]
    if not addressee_ids:
        return []
    addressees = db.query(User).filter(User.id.in_(addressee_ids)).all()
    return [_public_user_dict(u) for u in addressees]


@router.post("/me/friends/request")
def send_friend_request(
    user_id: Annotated[str, Query()],
    payload: Annotated[dict, Depends(get_jwt_payload)],
    db: Annotated[Session, Depends(get_db)],
):
    requester_id = uuid.UUID(payload.get("sub"))
    addressee_id = uuid.UUID(user_id)
    if requester_id == addressee_id:
        raise HTTPException(status_code=400, detail="Cannot add yourself")
    existing = db.query(Friendship).filter(
        or_(
            and_(Friendship.requester_id == requester_id, Friendship.addressee_id == addressee_id),
            and_(Friendship.requester_id == addressee_id, Friendship.addressee_id == requester_id),
        )
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Friend request already exists")
    row = Friendship(requester_id=requester_id, addressee_id=addressee_id, status="pending")
    db.add(row)
    db.commit()
    return {"status": "pending"}


@router.post("/me/friends/accept/{requester_id}")
def accept_friend_request(
    requester_id: str,
    payload: Annotated[dict, Depends(get_jwt_payload)],
    db: Annotated[Session, Depends(get_db)],
):
    addressee_id = uuid.UUID(payload.get("sub"))
    row = db.query(Friendship).filter(
        Friendship.requester_id == uuid.UUID(requester_id),
        Friendship.addressee_id == addressee_id,
        Friendship.status == "pending",
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Friend request not found")
    row.status = "accepted"
    db.commit()
    return {"status": "accepted"}


@router.delete("/me/friends/{friend_id}")
def remove_or_decline_friend(
    friend_id: str,
    payload: Annotated[dict, Depends(get_jwt_payload)],
    db: Annotated[Session, Depends(get_db)],
):
    user_id = uuid.UUID(payload.get("sub"))
    fid = uuid.UUID(friend_id)
    row = db.query(Friendship).filter(
        or_(
            and_(Friendship.requester_id == user_id, Friendship.addressee_id == fid),
            and_(Friendship.requester_id == fid, Friendship.addressee_id == user_id),
        )
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Friendship not found")
    db.delete(row)
    db.commit()
    return {"status": "removed"}


# ─── User search ──────────────────────────────────────────────────────────────

@router.get("/search")
def search_users(
    q: Annotated[str, Query(min_length=1)],
    payload: Annotated[dict, Depends(get_jwt_payload)],
    db: Annotated[Session, Depends(get_db)],
):
    me = payload.get("sub")
    results = (
        db.query(User)
        .filter(User.username.ilike(f"%{q}%"), User.id != me)
        .limit(20)
        .all()
    )
    return [_public_user_dict(u) for u in results]


# ─── Public user routes (must stay after /search and /me/*) ───────────────────

@router.get("/{user_id}/going-to")
def get_user_going_to(
    user_id: str,
    payload: Annotated[dict, Depends(get_jwt_payload)],
    db: Annotated[Session, Depends(get_db)],
):
    me = uuid.UUID(payload.get("sub"))
    them = uuid.UUID(user_id)
    if me != them and not _are_friends(db, me, them):
        raise HTTPException(status_code=403, detail="Not friends")
    user = db.query(User).filter(User.id == them).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"going_to_events": _going_to_ids(db, them)}


@router.get("/{user_id}/profile")
def get_user_profile(
    user_id: str,
    payload: Annotated[dict, Depends(get_jwt_payload)],
    db: Annotated[Session, Depends(get_db)],
):
    me = uuid.UUID(payload.get("sub"))
    them = uuid.UUID(user_id)
    user = db.query(User).filter(User.id == them).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    is_friend = me != them and _are_friends(db, me, them)
    favorites_count = (
        db.query(UserFavorite).filter(UserFavorite.user_id == them).count()
    )
    going_to_count = (
        db.query(UserGoingTo).filter(UserGoingTo.user_id == them).count()
    )
    return {
        **_public_user_dict(user),
        "is_friend": is_friend,
        "favorites_count": favorites_count,
        "going_to_count": going_to_count,
    }
