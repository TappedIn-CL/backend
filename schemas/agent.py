from pydantic import BaseModel
from typing import Optional


class AgentQueryRequest(BaseModel):
    query: str
    chips: list[str] = []
