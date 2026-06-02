from pydantic import BaseModel


class AgentQueryRequest(BaseModel):
    query: str
    chips: list[str] = []
    # TODO: consumed by the distance-ranking ticket. Accepted here only to
    # document the contract and avoid silently dropping the coords the
    # frontend sends; no node reads them yet.
    user_lat: float | None = None
    user_lng: float | None = None
