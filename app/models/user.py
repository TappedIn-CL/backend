from sqlalchemy import Column, Date, String, Integer, Boolean
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from db.session import Base
import uuid

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True, unique=True)

    # account tab
    email = Column(String, unique=True, index=True, nullable=False)
    username = Column(String, unique=True, index=True, nullable=True)

    # preferences tab
    vibes = Column(ARRAY(String), nullable=True)
    search_radius = Column(Integer, nullable=True) # lookup table in future?
    price_range = Column(String, nullable=True) # lookup table in future?
    preferred_days = Column(ARRAY(String), nullable=True) # lookup table in future?

    email_notifs = Column(Boolean, nullable=False, default=True) # lookup table in future?
    push_notifs = Column(Boolean, nullable=False, default=True) # lookup table in future?
    sms_notifs = Column(Boolean, nullable=False, default=True) # lookup table in future?

    # demographics tab
    date_of_birth = Column(Date, nullable=True)
    pronouns = Column(String, nullable=True) # lookup table in future?
    gender = Column(String, nullable=True) # lookup table in future?
    neighborhood = Column(String, nullable=True)
    occupation = Column(String, nullable=True)
    interests = Column(ARRAY(String), nullable=True)