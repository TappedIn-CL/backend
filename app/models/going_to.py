from sqlalchemy import Column, DateTime, ForeignKey, String, func
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
    # server_default=func.now() lets Postgres set the timestamp at INSERT
    # time, which is clock-skew-safe vs the app server's wall clock.
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    google_event_id = Column(String, nullable=True)
