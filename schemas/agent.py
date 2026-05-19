from pydantic import BaseModel


class AgentQueryRequest(BaseModel):
    query: str
    chips: list[str] = []
