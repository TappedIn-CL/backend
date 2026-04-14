from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from db.dependencies import get_db
from app.models.user import User
from schemas.user import UserCreate, UserResponse
from core.security import hash_password

router = APIRouter()

@router.post("/", response_model=UserResponse)
def create_user(user: UserCreate, db: Session = Depends(get_db)):

    existing_user = db.query(User).filter(User.username == user.username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already taken")
        
    hashed_pw = hash_password(user.password)

    db_user = User(
        username=user.username,
        password=hashed_pw
    )

    db.add(db_user)
    db.commit()
    db.refresh(db_user)

    return db_user