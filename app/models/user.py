from sqlalchemy import Column, Date, String
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from db.session import Base
import uuid

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True, unique=True)
    email = Column(String, unique=True, index=True, nullable=False)
    username = Column(String, unique=True, index=True, nullable=True)

    # user demographics
    date_of_birth = Column(Date, nullable=True)
    pronouns = Column(String, nullable=True) # lookup table in future?
    gender = Column(String, nullable=True) # lookup table in future?
    neighborhood = Column(String, nullable=True)
    occupation = Column(String, nullable=True)
    interests = Column(ARRAY(String), nullable=True)