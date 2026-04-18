from pydantic import BaseModel
import uuid

class UserCreate(BaseModel):
    email: str
    username: str
    password: str

class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    username: str

    class Config:
        from_attributes = True