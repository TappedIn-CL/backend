from pydantic import BaseModel, EmailStr
from uuid import UUID
from datetime import date

from sqlalchemy import Column

class UserCreate(BaseModel):
    email: EmailStr
    username: str | None = None

    # user demographics
    date_of_birth: date | None = None
    pronouns: str | None = None
    gender: str | None = None
    neighborhood: str | None = None
    occupation: str | None = None
    interests: list[str] | None = None

class UserResponse(BaseModel):
    id: UUID
    email: EmailStr
    username: str | None = None
    
    # user demographics
    date_of_birth: date | None = None
    pronouns: str | None = None
    gender: str | None = None
    neighborhood: str | None = None
    occupation: str | None = None
    interests: list[str] | None = None

    class Config:
        from_attributes = True