from pydantic import BaseModel
import uuid

class UserCreate(BaseModel):
    username: str
    password: str

class UserResponse(BaseModel):
    id: uuid.UUID
    username: str

    class Config:
        from_attributes = True