from datetime import datetime
import uuid

from pydantic import BaseModel, ConfigDict, Field


class EventCreate(BaseModel):
    title: str
    date: datetime
    cost: float = Field(ge=0)

    description: str | None = None
    location: str | None = None
    category: str | None = None


class EventResponse(BaseModel):
    id: uuid.UUID
    title: str
    date: datetime
    cost: float

    description: str | None = None
    location: str | None = None
    category: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
