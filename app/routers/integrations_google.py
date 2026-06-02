"""Google Calendar OAuth connection (separate from Supabase identity login).

The user-id round-trip through Google is protected by an HMAC-signed `state`
param so the callback can't be forged or replayed.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow
from sqlalchemy.orm import Session

from app.models.google_credentials import GoogleCredentials
from auth.deps import get_supabase_sub
from db.dependencies import get_db

router = APIRouter()

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
STATE_TTL_SECONDS = 600


def _client_config() -> dict:
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    redirect_uri = os.environ.get("GOOGLE_OAUTH_REDIRECT_URI")
    if not (client_id and client_secret and redirect_uri):
        raise HTTPException(status_code=500, detail="Google OAuth env not configured")
    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        }
    }


def _state_secret() -> bytes:
    secret = os.environ.get("GOOGLE_OAUTH_STATE_SECRET")
    if not secret:
        raise HTTPException(status_code=500, detail="GOOGLE_OAUTH_STATE_SECRET not configured")
    return secret.encode("utf-8")


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _sign_state(user_id: str) -> str:
    payload = {"uid": user_id, "nonce": secrets.token_urlsafe(8), "exp": int(time.time()) + STATE_TTL_SECONDS}
    payload_b64 = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = hmac.new(_state_secret(), payload_b64.encode("ascii"), hashlib.sha256).digest()
    return f"{payload_b64}.{_b64url(sig)}"


def _verify_state(state: str) -> str:
    try:
        payload_b64, sig_b64 = state.split(".", 1)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid state")

    expected_sig = hmac.new(_state_secret(), payload_b64.encode("ascii"), hashlib.sha256).digest()
    try:
        given_sig = _b64url_decode(sig_b64)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid state")
    if not hmac.compare_digest(expected_sig, given_sig):
        raise HTTPException(status_code=400, detail="State signature mismatch")

    try:
        payload = json.loads(_b64url_decode(payload_b64))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid state payload")

    if int(payload.get("exp", 0)) < int(time.time()):
        raise HTTPException(status_code=400, detail="State expired")

    uid = payload.get("uid")
    if not isinstance(uid, str) or not uid:
        raise HTTPException(status_code=400, detail="Invalid state subject")
    return uid


@router.get("/connect")
def connect(
    user_id: Annotated[str, Depends(get_supabase_sub)],
) -> dict:
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES)
    flow.redirect_uri = os.environ["GOOGLE_OAUTH_REDIRECT_URI"]
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=_sign_state(user_id),
    )
    return {"auth_url": auth_url}


@router.get("/callback")
def callback(
    code: Annotated[str, Query()],
    state: Annotated[str, Query()],
    db: Annotated[Session, Depends(get_db)],
):
    user_id = _verify_state(state)

    flow = Flow.from_client_config(_client_config(), scopes=SCOPES)
    flow.redirect_uri = os.environ["GOOGLE_OAUTH_REDIRECT_URI"]
    flow.fetch_token(code=code)
    creds = flow.credentials

    if not creds.refresh_token:
        # Google only returns a refresh token on first consent. `prompt=consent`
        # should force it; if we still don't have one, fail loudly so we don't
        # store a half-broken row.
        raise HTTPException(status_code=400, detail="No refresh token returned from Google")

    row = db.query(GoogleCredentials).filter(GoogleCredentials.user_id == user_id).first()
    if row is None:
        row = GoogleCredentials(user_id=user_id)
        db.add(row)

    row.access_token = creds.token
    row.refresh_token = creds.refresh_token
    row.token_uri = creds.token_uri
    row.scopes = list(creds.scopes) if creds.scopes else SCOPES
    row.expiry = creds.expiry
    row.updated_at = datetime.utcnow()
    db.commit()

    frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:5173")
    return RedirectResponse(url=f"{frontend_url}/profile?google=connected")
