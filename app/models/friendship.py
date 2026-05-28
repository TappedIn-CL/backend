from sqlalchemy import Column, DateTime, String, UniqueConstraint, ForeignKey, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from db.session import Base
from datetime import datetime
import uuid


class Friendship(Base):
    __tablename__ = "friendships"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    requester_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    addressee_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # "pending" = request sent, not yet accepted; "accepted" = mutual friends
    status = Column(String, nullable=False, default="pending")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("requester_id", "addressee_id", name="uq_friendship_pair"),
        CheckConstraint("status IN ('pending', 'accepted')", name="ck_friendship_status"),
    )
