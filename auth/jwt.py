import os
from typing import Any

import jwt as pyjwt
from dotenv import load_dotenv
from fastapi import HTTPException

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")
EXPECTED_ISSUER = f"{SUPABASE_URL}/auth/v1" if SUPABASE_URL else None

# JWKS client caches keys and re-fetches when a new kid appears
_jwks_client: pyjwt.PyJWKClient | None = None
if SUPABASE_URL:
    _jwks_client = pyjwt.PyJWKClient(
        f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json",
        cache_keys=True,
    )


def verify_jwt(token: str) -> dict[str, Any]:
    decode_options = {
        "algorithms": ["ES256", "RS256", "HS256"],
        "audience": "authenticated",
        **({"issuer": EXPECTED_ISSUER} if EXPECTED_ISSUER else {}),
    }

    # Try asymmetric verification via JWKS (newer Supabase projects use ES256/RS256)
    if _jwks_client:
        try:
            signing_key = _jwks_client.get_signing_key_from_jwt(token)
            return pyjwt.decode(token, signing_key.key, **decode_options)
        except pyjwt.exceptions.PyJWTError as e:
            print(f"[JWT DEBUG] JWKS path failed: {type(e).__name__}: {e}")

    # Fall back to symmetric HS256 with the project JWT secret
    if SUPABASE_JWT_SECRET:
        hs256_options = {
            **decode_options,
            "algorithms": ["HS256"],
        }
        try:
            return pyjwt.decode(token, SUPABASE_JWT_SECRET, **hs256_options)
        except pyjwt.exceptions.PyJWTError as e:
            print(f"[JWT DEBUG] HS256 path failed: {type(e).__name__}: {e}")

    raise HTTPException(status_code=401, detail="Invalid or expired token")
