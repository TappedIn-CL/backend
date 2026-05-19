from typing import Annotated
from fastapi import APIRouter, Depends
from auth.deps import get_jwt_payload

from requests import Session
from db.dependencies import get_db
from app.models.user import User

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

            # favorite events
            "favorite_events": user.favorite_events,
        }
    
    return {"message": "user not found in database, but JWT is valid."}

@router.get("/me/favorites")
def read_favorite_events(
    payload: Annotated[dict, Depends(get_jwt_payload)],
    db: Annotated[Session, Depends(get_db)],
):
    id = payload.get("sub")
    user = db.query(User).filter(User.id == id).first()

    if user:
        return {
            "favorite_events": user.favorite_events or [],
        }
    
    return {"message": "user not found in database, but JWT is valid."}

@router.post("/me/favorites")
def add_favorite_event(
    event_id: str,
    payload: Annotated[dict, Depends(get_jwt_payload)],
    db: Annotated[Session, Depends(get_db)],
):
    id = payload.get("sub")
    user = db.query(User).filter(User.id == id).first()

    if user:
        favorite_events = user.favorite_events or []
        
        if event_id not in favorite_events:
            user.favorite_events = favorite_events + [event_id] # avoid mutating the list in-place if it's already set since SQLAlchemy can be picky about this
            db.commit()
            return {"message": "Event added to favorites."}
        else:
            return {"message": "Event already in favorites."}

    return {"message": "user not found in database, but JWT is valid."}

@router.delete("/me/favorites/{event_id}")
def remove_favorite_event(
    event_id: str,
    payload: Annotated[dict, Depends(get_jwt_payload)],
    db: Annotated[Session, Depends(get_db)],
):
    id = payload.get("sub")
    user = db.query(User).filter(User.id == id).first()

    if user:
        favorite_events = user.favorite_events or []
        if event_id in favorite_events:
            user.favorite_events = [e for e in favorite_events if e != event_id]
            db.commit()
            return {"message": "Event removed from favorites."}
        else:
            return {"message": "Event not found in favorites."}

    return {"message": "user not found in database, but JWT is valid."}