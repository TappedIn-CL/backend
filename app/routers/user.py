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
    email = payload.get("email")
    user = db.query(User).filter(User.email == email).first()

    if User:
        return user
    
    return {"message": "user not found in database, but JWT is valid."}