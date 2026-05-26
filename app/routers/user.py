from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.models.event import Event
from app.models.favorite import UserFavorite
from app.models.user import User
from app.utils.event_utils import event_to_hydrated
from auth.deps import get_jwt_payload, get_supabase_sub
from db.dependencies import get_db
from schemas.event import HydratedEventResponse
from schemas.user import FavoriteCreate, FavoriteResponse

router = APIRouter()


@router.get("/me")
def read_me(
    payload: Annotated[dict, Depends(get_jwt_payload)],
    db: Annotated[Session, Depends(get_db)],
):
    id = payload.get("sub")
    user = db.query(User).filter(User.id == id).first()

    if user:
        return {
            # profile page
            "id": user.id,
            "email": user.email,
            "username": user.username,
            "full_name": user.full_name,
            "phone_number": user.phone_number,

            # preferences tab
            "vibes": user.vibes,
            "search_radius": user.search_radius,
            "price_range": user.price_range,
            "preferred_days": user.preferred_days,

            "email_notifs": user.email_notifs,
            "push_notifs": user.push_notifs,
            "sms_notifs": user.sms_notifs,

            # demographics tab
            "date_of_birth": user.date_of_birth,
            "pronouns": user.pronouns,
            "gender": user.gender,
            "neighborhood": user.neighborhood,
            "occupation": user.occupation,
            "interests": user.interests,
        }

    return {"message": "user not found in database, but JWT is valid."}


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
    # Confirm the event exists so we don't store dangling references.
    # FK would catch this at flush time, but pre-checking gives a clean 404.
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
