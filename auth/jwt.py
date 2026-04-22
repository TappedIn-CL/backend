import os
import time
from typing import Any

import requests
from dotenv import load_dotenv
from fastapi import HTTPException
from jose import jwk, jwt

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
JWKS_URL = f"{SUPABASE_URL}/auth/v1/keys" if SUPABASE_URL else ""
# Supabase sets iss to this for user JWTs
EXPECTED_ISSUER = f"{SUPABASE_URL}/auth/v1" if SUPABASE_URL else None

_jwks_data: dict[str, Any] | None = None
_jwks_fetched_at: float = 0.0
JWKS_TTL_SEC = 300


def _fetch_jwks() -> dict[str, Any]:
    if not JWKS_URL:
        raise HTTPException(
            status_code=500,
            detail="SUPABASE_URL is not set; cannot verify JWTs.",
        )
    try:
        response = requests.get(JWKS_URL, timeout=10)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Could not fetch Supabase JWKS: {exc}",
        ) from exc
    return response.json()


def get_jwks(*, refresh: bool = False) -> dict[str, Any]:
    """Return JWKS JSON; refresh from Supabase when stale or refresh=True."""
    global _jwks_data, _jwks_fetched_at
    now = time.time()
    if (
        refresh
        or _jwks_data is None
        or now - _jwks_fetched_at > JWKS_TTL_SEC
    ):
        _jwks_data = _fetch_jwks()
        _jwks_fetched_at = now
    return _jwks_data


def _key_for_kid(jwks: dict[str, Any], kid: str) -> Any | None:
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            return jwk.construct(key)
    return None


def verify_jwt(token: str) -> dict[str, Any]:
    """
    Verify a Supabase access JWT (RS256) and return claims.
    Refreshes JWKS once if the key id is unknown (key rotation).
    """
    try:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        if not kid:
            raise HTTPException(status_code=401, detail="Invalid token header")

        jwks = get_jwks()
        signing_key = _key_for_kid(jwks, kid)
        if signing_key is None:
            jwks = get_jwks(refresh=True)
            signing_key = _key_for_kid(jwks, kid)
        if signing_key is None:
            raise HTTPException(status_code=401, detail="Unknown signing key")

        decode_kwargs: dict[str, Any] = {
            "algorithms": ["RS256"],
            "audience": "authenticated",
        }
        if EXPECTED_ISSUER:
            decode_kwargs["issuer"] = EXPECTED_ISSUER

        return jwt.decode(token, signing_key, **decode_kwargs)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
        ) from None
