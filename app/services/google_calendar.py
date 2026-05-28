"""Google Calendar sync for "Going To" events.

Profile-state writes succeed independently of GCal sync. The route layer catches
CalendarSyncError and surfaces a non-blocking failure to the client; all failure
modes collapse to a small closed set of reasons.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from sqlalchemy.orm import Session

from app.models.event import Event
from app.models.google_credentials import GoogleCredentials

logger = logging.getLogger(__name__)

DEFAULT_EVENT_TZ = "America/Los_Angeles"
DEFAULT_DURATION = timedelta(hours=2)
CALENDAR_ID = "primary"


class CalendarSyncError(Exception):
    """Raised when GCal sync fails. `reason` is one of: needs_reconnect, unknown."""

    def __init__(self, reason: str, *, message: str | None = None) -> None:
        super().__init__(message or reason)
        self.reason = reason


def _load_credentials(user_id: str, db: Session) -> Credentials:
    row = db.query(GoogleCredentials).filter(GoogleCredentials.user_id == user_id).first()
    if row is None:
        raise CalendarSyncError("needs_reconnect", message="No Google credentials")

    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise CalendarSyncError("unknown", message="Google client env not configured")

    creds = Credentials(
        token=row.access_token,
        refresh_token=row.refresh_token,
        token_uri=row.token_uri,
        client_id=client_id,
        client_secret=client_secret,
        scopes=list(row.scopes) if row.scopes else None,
        expiry=row.expiry,
    )

    if not creds.valid:
        try:
            creds.refresh(Request())
        except RefreshError as e:
            raise CalendarSyncError("needs_reconnect", message=str(e)) from e

        row.access_token = creds.token
        row.expiry = creds.expiry
        db.commit()

    return creds


def _get_service(user_id: str, db: Session):
    creds = _load_credentials(user_id, db)
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def insert_event(user_id: str, db: Session, event: Event) -> str:
    """Insert event into the user's primary calendar; return the new GCal event id."""
    service = _get_service(user_id, db)

    start = event.date
    end = start + DEFAULT_DURATION
    body = {
        "summary": event.title,
        "location": event.location,
        "description": event.description,
        "start": {"dateTime": start.isoformat(), "timeZone": DEFAULT_EVENT_TZ},
        "end": {"dateTime": end.isoformat(), "timeZone": DEFAULT_EVENT_TZ},
        "extendedProperties": {
            "private": {"tappedin_event_id": str(event.id)},
        },
    }

    try:
        created = service.events().insert(calendarId=CALENDAR_ID, body=body).execute()
    except HttpError as e:
        status = getattr(e.resp, "status", None)
        if status in (401, 403):
            raise CalendarSyncError("needs_reconnect", message=str(e)) from e
        logger.exception("GCal insert failed for user %s event %s", user_id, event.id)
        raise CalendarSyncError("unknown", message=str(e)) from e

    return created["id"]


def delete_event(user_id: str, db: Session, google_event_id: str) -> None:
    """Best-effort delete; swallows 404/410 (already gone)."""
    service = _get_service(user_id, db)
    try:
        service.events().delete(calendarId=CALENDAR_ID, eventId=google_event_id).execute()
    except HttpError as e:
        status = getattr(e.resp, "status", None)
        if status in (404, 410):
            return
        if status in (401, 403):
            raise CalendarSyncError("needs_reconnect", message=str(e)) from e
        logger.exception("GCal delete failed for user %s event %s", user_id, google_event_id)
        raise CalendarSyncError("unknown", message=str(e)) from e
