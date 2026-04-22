from sqlalchemy import Column, String, Integer
from sqlalchemy.dialects.postgresql import UUID
from db.session import Base
import uuid

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True)
    email = Column(String, unique=True, index=True, nullable=False)
    username = Column(String, unique=True, index=True, nullable=True)

    # user demographics
    age = Column(Integer, nullable=True)
    gender = Column(String, nullable=True)
    location = Column(String, nullable=True)
    interests = Column(String, nullable=True)  # comma-separated interests
