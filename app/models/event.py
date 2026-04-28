from sqlalchemy import Column, DateTime, Float, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import validates
from datetime import datetime
import uuid


from db.session import Base


ALLOWED_EVENT_CATEGORIES = {
    "Music",
    "Food & Drink",
    "Art & Culture",
    "Nightlife",
    "Comedy",
    "Wellness",
    "Networking",
}

ALLOWED_SPECIAL_TAGS = {
    "Outdoor",
    "Indoor",
    "21+",
    "Family-friendly",
    "Limited spots",
    "Pop-up",
    "Free perks",
}

VIBE_TAGS = {
    "Chill",
    "Energetic",
    "Intimate",
    "Social",
    "Creative",
    "Hyped",
    "Educational",
}


class Event(Base):
    __tablename__ = "events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True)
    title = Column(String, nullable=False, index=True)
    description = Column(String, nullable=True)
    date = Column(DateTime, nullable=False, index=True)
    cost = Column(Float, nullable=False)
    location = Column(String, nullable=True)
    category = Column(String, nullable=True)
    special_tags = Column(String, nullable=True)
    vibe_tags = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    @validates("category")
    def validate_category(self, key: str, value: str | None) -> str | None:
        if value is None:
            return value
        if value not in ALLOWED_EVENT_CATEGORIES:
            raise ValueError(
                "Invalid category. Must be one of: "
                + ", ".join(sorted(ALLOWED_EVENT_CATEGORIES))
            )
        return value

    @validates("special_tags")
    def validate_special_tags(self, key: str, value: str | None) -> str | None:
        if value is None:
            return value
        tags = [tag.strip() for tag in value.split(",") if tag.strip()]
        if not all(tag in ALLOWED_SPECIAL_TAGS for tag in tags):
            raise ValueError(
                "Invalid special tags. Must be a comma-separated list of: "
                + ", ".join(sorted(ALLOWED_SPECIAL_TAGS))
            )
        return value
    
    @validates("vibe_tags")
    def validate_vibe_tags(self, key: str, value: str | None) -> str | None:
        if value is None:
            return value
        tags = [tag.strip() for tag in value.split(",") if tag.strip()]
        if not all(tag in VIBE_TAGS for tag in tags):
            raise ValueError(
                "Invalid vibe tags. Must be a comma-separated list of: "
                + ", ".join(sorted(VIBE_TAGS))
            )
        return value
