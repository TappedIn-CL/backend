from datetime import datetime
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# Must stay in lock-step with agent/taxonomy.py CATEGORIES.
# Literal can't be built from a list at runtime, so the values are inline —
# the Event SQLAlchemy validator imports CATEGORIES directly and will 500
# at startup if these drift apart, which is the trip-wire.
EventCategory = Literal[
    "Music",
    "Food & Drink",
    "Arts",
    "Nightlife",
    "Comedy",
    "Wellness",
    "Networking",
    "Sports",
    "Family",
    "Fashion",
    "Other",
]

# Must stay in lock-step with agent/taxonomy.py SPECIAL_TAGS.
SpecialTag = Literal[
    "outdoor",
    "indoor",
    "21+",
    "family-friendly",
    "limited-spots",
    "pop-up",
    "free-perks",
    "free",
]

# Must stay in lock-step with agent/taxonomy.py VIBE_TAGS.
VibeTag = Literal[
    "chill",
    "energetic",
    "intimate",
    "social",
    "creative",
    "hyped",
    "educational",
    "adventurous",
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
    source: str | None = None
    source_id: str | None = None


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
    source: str | None = None
    source_id: str | None = None
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


class HydratedEventResponse(BaseModel):
    # Deliberately permissive `str` types for category / tags / vibe_tags
    # instead of the Literal aliases above. Hydration is the last stop before
    # the frontend, so the schema is intentionally lenient: any legacy DB row
    # written before vocab alignment (or a tag/vibe drift that's still
    # unresolved) should still serialize and render, not 422.
    id: uuid.UUID
    title: str
    description: str | None = None
    category: str | None = None
    tags: list[str] = []
    vibe_tags: list[str] = []
    venue_name: str | None = None
    address: str | None = None
    city: str = "Los Angeles"
    latitude: float | None = None
    longitude: float | None = None
    price_min: float | None = None
    price_max: float | None = None
    start_time: str | None = None
    end_time: str | None = None
    image_url: str | None = None
    source_url: str | None = None

    model_config = ConfigDict(from_attributes=True)
