from typing import Optional

from pydantic import BaseModel


class AgentQueryRequest(BaseModel):
    query: str
    chips: list[str] = []
    user_lat: Optional[float] = None  # user location; None if not shared
    user_lng: Optional[float] = None
