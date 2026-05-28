from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.models.event import Event
from app.models.favorite import UserFavorite
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
)

router = APIRouter()


@router.get("/me")
def read_me(
    payload: Annotated[dict, Depends(get_jwt_payload)],
    db: Annotated[Session, Depends(get_db)],
):
    id = payload.get("sub")
    user = db.query(User).filter(User.id == id).first()

    if user:
        favorite_ids = [
            str(row.event_id)
            for row in db.query(UserFavorite.event_id)
            .filter(UserFavorite.user_id == id)
            .all()
        ]
        going_to_ids = [
            str(row.event_id)
            for row in db.query(UserGoingTo.event_id)
            .filter(UserGoingTo.user_id == id)
            .all()
        ]
        gcal_connected = (
            db.query(GoogleCredentials.user_id)
            .filter(GoogleCredentials.user_id == id)
            .first()
            is not None
        )

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

            # event lists
            "favorite_events": favorite_ids,
            "going_to_events": going_to_ids,

            # integrations
            "google_calendar_connected": gcal_connected,
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
