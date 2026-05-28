from sqlalchemy import Column, Date, String, Integer, Boolean, Text
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from db.session import Base
import uuid

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True, unique=True)

    # account tab
    email = Column(String, unique=True, index=True, nullable=False)
    username = Column(String, unique=True, index=True, nullable=True)
    full_name = Column(String, nullable=True)
    phone_number = Column(String, nullable=True)
    avatar_url = Column(Text, nullable=True)

    # preferences tab
    vibes = Column(ARRAY(String), nullable=True)
    search_radius = Column(Integer, nullable=True)
    price_range = Column(String, nullable=True)
    preferred_days = Column(ARRAY(String), nullable=True)

    email_notifs = Column(Boolean, nullable=False, default=True)
    push_notifs = Column(Boolean, nullable=False, default=True)
    sms_notifs = Column(Boolean, nullable=False, default=True)

    # demographics tab
    date_of_birth = Column(Date, nullable=True)
    pronouns = Column(String, nullable=True)
    gender = Column(String, nullable=True)
    neighborhood = Column(String, nullable=True)
    occupation = Column(String, nullable=True)
    interests = Column(ARRAY(String), nullable=True)

    # legacy array — prefer user_favorites junction table for new writes
    favorite_events = Column(ARRAY(String), nullable=True)
    going_to_events = Column(ARRAY(String), nullable=True)
