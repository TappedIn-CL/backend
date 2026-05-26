import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, and_
from sqlalchemy.orm import Session

from auth.deps import get_jwt_payload
from db.dependencies import get_db
from app.models.user import User
from app.models.friendship import Friendship
from schemas.user import UserUpdate

router = APIRouter()


def _user_to_dict(user: User) -> dict:
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
        "favorite_events": user.favorite_events or [],
        "going_to_events": user.going_to_events or [],
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
    return db.query(Friendship).filter(
        Friendship.status == "accepted",
        or_(
            and_(Friendship.requester_id == user_a, Friendship.addressee_id == user_b),
            and_(Friendship.requester_id == user_b, Friendship.addressee_id == user_a),
        ),
    ).first() is not None


# ─── /me ──────────────────────────────────────────────────────────────────────

@router.get("/me")
def read_me(
    payload: Annotated[dict, Depends(get_jwt_payload)],
    db: Annotated[Session, Depends(get_db)],
):
    user = _get_or_create_user(payload, db)
    return _user_to_dict(user)


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
    return _user_to_dict(user)


# ─── Favorites ────────────────────────────────────────────────────────────────

@router.get("/me/favorites")
def get_favorites(
    payload: Annotated[dict, Depends(get_jwt_payload)],
    db: Annotated[Session, Depends(get_db)],
):
    user_id = payload.get("sub")
    user = db.query(User).filter(User.id == user_id).first()
    return {"favorite_events": user.favorite_events or [] if user else []}


@router.post("/me/favorites")
def add_favorite(
    event_id: Annotated[str, Query()],
    payload: Annotated[dict, Depends(get_jwt_payload)],
    db: Annotated[Session, Depends(get_db)],
):
    user_id = payload.get("sub")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    favorites = list(user.favorite_events or [])
    if event_id not in favorites:
        favorites.append(event_id)
        user.favorite_events = favorites
        db.commit()
    return {"favorite_events": favorites}


@router.delete("/me/favorites/{event_id}")
def remove_favorite(
    event_id: str,
    payload: Annotated[dict, Depends(get_jwt_payload)],
    db: Annotated[Session, Depends(get_db)],
):
    user_id = payload.get("sub")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    favorites = [f for f in (user.favorite_events or []) if f != event_id]
    user.favorite_events = favorites
    db.commit()
    return {"favorite_events": favorites}


# ─── Going To ─────────────────────────────────────────────────────────────────

@router.get("/me/going-to")
def get_going_to(
    payload: Annotated[dict, Depends(get_jwt_payload)],
    db: Annotated[Session, Depends(get_db)],
):
    user_id = payload.get("sub")
    user = db.query(User).filter(User.id == user_id).first()
    return {"going_to_events": user.going_to_events or [] if user else []}


@router.post("/me/going-to")
def add_going_to(
    event_id: Annotated[str, Query()],
    payload: Annotated[dict, Depends(get_jwt_payload)],
    db: Annotated[Session, Depends(get_db)],
):
    user_id = payload.get("sub")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    going_to = list(user.going_to_events or [])
    if event_id not in going_to:
        going_to.append(event_id)
        user.going_to_events = going_to
        db.commit()
    return {"going_to_events": going_to}


@router.delete("/me/going-to/{event_id}")
def remove_going_to(
    event_id: str,
    payload: Annotated[dict, Depends(get_jwt_payload)],
    db: Annotated[Session, Depends(get_db)],
):
    user_id = payload.get("sub")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    going_to = [e for e in (user.going_to_events or []) if e != event_id]
    user.going_to_events = going_to
    db.commit()
    return {"going_to_events": going_to}


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
    requesters = db.query(User).filter(User.id.in_(requester_ids)).all()
    return [_public_user_dict(r) for r in requesters]


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


# ─── Public user routes ───────────────────────────────────────────────────────

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
    return {"going_to_events": user.going_to_events or []}


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
    return {
        **_public_user_dict(user),
        "is_friend": is_friend,
        "favorites_count": len(user.favorite_events or []),
        "going_to_count": len(user.going_to_events or []),
    }
