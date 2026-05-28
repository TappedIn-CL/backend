from pydantic import BaseModel
from uuid import UUID
from datetime import datetime


class RSVPCreate(BaseModel):
    event_id: UUID

class RSVPResponse(BaseModel):
    id: UUID
    
    user_id: UUID
    event_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True