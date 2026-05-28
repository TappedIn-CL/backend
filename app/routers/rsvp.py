from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.models.event import Event
from app.models.rsvp import RSVP
from app.models.user import User
from auth.deps import get_supabase_sub
from db.dependencies import get_db
from schemas.rsvp import RSVPCreate, RSVPResponse


router = APIRouter()


@router.post("/me/rsvps", response_model=RSVPResponse, status_code=status.HTTP_201_CREATED)
def create_rsvp(
    rsvp_data: RSVPCreate,
    supabase_sub: Annotated[str, Depends(get_supabase_sub)],
    db: Annotated[Session, Depends(get_db)],
):
    user_id = UUID(supabase_sub)

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    event = db.query(Event).filter(Event.id == rsvp_data.event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    existing_rsvp = (
        db.query(RSVP)
        .filter(RSVP.user_id == user_id, RSVP.event_id == rsvp_data.event_id)
        .first()
    )

    if existing_rsvp:
        return existing_rsvp

    rsvp = RSVP(user_id=user_id, event_id=rsvp_data.event_id)
    db.add(rsvp)

    event_id_str = str(rsvp_data.event_id)

    if user.favorite_events is None:
        user.favorite_events = []

    if event_id_str not in user.favorite_events:
        user.favorite_events = user.favorite_events + [event_id_str]

    db.commit()
    db.refresh(rsvp)

    return rsvp


@router.get("/me/rsvps", response_model=list[RSVPResponse])
def get_rsvps(
    supabase_sub: Annotated[str, Depends(get_supabase_sub)],
    db: Annotated[Session, Depends(get_db)],
):
    user_id = UUID(supabase_sub)

    return (
        db.query(RSVP)
        .filter(RSVP.user_id == user_id)
        .order_by(RSVP.created_at.desc())
        .all()
    )


@router.delete("/me/rsvps/{event_id}")
def delete_rsvp(
    event_id: UUID,
    supabase_sub: Annotated[str, Depends(get_supabase_sub)],
    db: Annotated[Session, Depends(get_db)],
):
    user_id = UUID(supabase_sub)

    rsvp = (
        db.query(RSVP)
        .filter(RSVP.user_id == user_id, RSVP.event_id == event_id)
        .first()
    )

    if not rsvp:
        raise HTTPException(status_code=404, detail="RSVP not found")

    db.delete(rsvp)
    db.commit()

    return {"message": "RSVP deleted"}