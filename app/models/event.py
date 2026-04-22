from sqlalchemy import Column, DateTime, Float, String
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid


from db.session import Base


class Event(Base):
    __tablename__ = "events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True)
    title = Column(String, nullable=False, index=True)
    description = Column(String, nullable=True)
    date = Column(DateTime, nullable=False, index=True)
    cost = Column(Float, nullable=False)
    location = Column(String, nullable=True)
    category = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
