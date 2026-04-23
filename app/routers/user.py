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
            "id": user.id,
            "email": user.email,
            "username": user.username,
            "age": user.age,
            "gender": user.gender,
            "location": user.location,
            "interests": user.interests,
        }
    
    return {"message": "user not found in database, but JWT is valid."}