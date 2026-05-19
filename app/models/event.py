from sqlalchemy import Column, DateTime, Float, String, UniqueConstraint, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import validates
from datetime import datetime
import uuid


from agent.taxonomy import CATEGORIES, SPECIAL_TAGS, VIBE_TAGS as TAXONOMY_VIBE_TAGS
from db.session import Base


# Source of truth for category/tag/vibe vocabulary lives in agent/taxonomy.py.
# Importing the sets here keeps the DB validator, the LLM enrichment prompt,
# and the Pinecone filter contract aligned on a single list. Lowercase is the
# canonical convention (see taxonomy.py); legacy capitalized values in this
# file were the source of the drift fixed in this change.
ALLOWED_EVENT_CATEGORIES = set(CATEGORIES)
ALLOWED_SPECIAL_TAGS = set(SPECIAL_TAGS)
VIBE_TAGS = set(TAXONOMY_VIBE_TAGS)


class Event(Base):
    __tablename__ = "events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True)
    title = Column(String, nullable=False, index=True)
    description = Column(String, nullable=True)
    date = Column(DateTime, nullable=False, index=True)
    cost = Column(Float, nullable=False)
    location = Column(String, nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    category = Column(String, nullable=True)
    special_tags = Column(String, nullable=True)
    vibe_tags = Column(String, nullable=True)
    source = Column(String, nullable=True)
    source_id = Column(String, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint('source', 'source_id', name='uq_events_source_source_id'),
    )

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
