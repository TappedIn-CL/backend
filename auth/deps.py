from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from auth.jwt import verify_jwt

security = HTTPBearer(auto_error=False)


def get_bearer_token(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(security),
    ],
) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials


def get_jwt_payload(token: Annotated[str, Depends(get_bearer_token)]) -> dict:
    return verify_jwt(token)


def get_optional_jwt_payload(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(security),
    ],
) -> dict | None:
    """Returns JWT claims if a valid token is present, None otherwise."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        return None
    try:
        return verify_jwt(credentials.credentials)
    except HTTPException:
        return None


def get_supabase_sub(
    payload: Annotated[dict, Depends(get_jwt_payload)],
) -> str:
    sub = payload.get("sub")
    if not sub or not isinstance(sub, str):
        raise HTTPException(status_code=401, detail="Invalid token subject")
    return sub
