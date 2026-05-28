from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID

from db.session import Base


class UserGoingTo(Base):
    __tablename__ = "user_going_to"

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    event_id = Column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    google_event_id = Column(String, nullable=True)
