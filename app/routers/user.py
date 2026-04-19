from typing import Annotated

from fastapi import APIRouter, Depends

from auth.deps import get_jwt_payload

router = APIRouter()


@router.get("/me")
def read_me(payload: Annotated[dict, Depends(get_jwt_payload)]):
    """Requires `Authorization: Bearer <Supabase access_token>`."""
    return {
        "sub": payload.get("sub"),
        "email": payload.get("email"),
        "role": payload.get("role"),
    }
