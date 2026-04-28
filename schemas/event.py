from datetime import datetime
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


EventCategory = Literal[
    "Music",
    "Food & Drink",
    "Art & Culture",
    "Nightlife",
    "Comedy",
    "Wellness",
    "Networking",
]

SpecialTag = Literal[
    "Outdoor",
    "Indoor",
    "21+",
    "Family-friendly",
    "Limited spots",
    "Pop-up",
    "Free perks",
]

VibeTag = Literal[
    "Chill",
    "Energetic",
    "Intimate",
    "Social",
    "Creative",
    "Hyped",
    "Educational",
]

class EventCreate(BaseModel):
    title: str
    date: datetime
    cost: float = Field(ge=0)

    description: str | None = None
    location: str | None = None
    category: EventCategory | None = None
    special_tags: list[SpecialTag] | None = None
    vibe_tags: list[VibeTag] | None = None


class EventResponse(BaseModel):
    id: uuid.UUID
    title: str
    date: datetime
    cost: float

    description: str | None = None
    location: str | None = None
    category: EventCategory | None = None
    special_tags: list[SpecialTag] | None = None
    vibe_tags: list[VibeTag] | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_validator("special_tags", "vibe_tags", mode="before")
    @classmethod
    def parse_tags(cls, v: str | list | None) -> list | None:
        """Parse comma-separated string tags to list, or pass through lists."""
        if v is None:
            return None
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            return [tag.strip() for tag in v.split(",") if tag.strip()]
        return None
