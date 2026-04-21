from pydantic import BaseModel, EmailStr
import uuid

class UserCreate(BaseModel):
    email: EmailStr
    username: str

    age: int | None = None
    gender: str | None = None
    location: str | None = None
    interests: str | None = None # comma-separated interests

class UserResponse(BaseModel):
    id: uuid.UUID
    email: EmailStr
    username: str | None = None
    age: int | None = None
    gender: str | None = None
    location: str | None = None
    interests: str | None = None  # comma-separated interests

    class Config:
        from_attributes = True