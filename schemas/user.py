from pydantic import BaseModel, EmailStr
from uuid import UUID
from datetime import date

class UserCreate(BaseModel):
    # account tab
    email: EmailStr
    username: str | None = None
    full_name: str | None = None
    phone_number: str | None = None

    # preferences tab
    vibes: list[str] | None = None
    search_radius: int | None = None
    price_range: str | None = None
    preferred_days: list[str] | None = None

    email_notifs: bool | None = None
    push_notifs: bool | None = None
    sms_notifs: bool | None = None

    # demographics tab
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

    # account tab
    full_name: str | None = None
    phone_number: str | None = None

    # preferences tab
    vibes: list[str] | None = None
    search_radius: int | None = None
    price_range: str | None = None
    preferred_days: list[str] | None = None

    email_notifs: bool
    push_notifs: bool
    sms_notifs: bool
    
    # demographics tab
    date_of_birth: date | None = None
    pronouns: str | None = None
    gender: str | None = None
    neighborhood: str | None = None
    occupation: str | None = None
    interests: list[str] | None = None

    class Config:
        from_attributes = True