"""
Daily Pinecone cleanup.

Removes the search-index vectors for events that are past their end time so they
stop surfacing in semantic search / "for you" results. Supabase rows are kept
untouched — they're the historical record and are soft-deleted separately via
the `is_active` flag (see app/utils/event_utils.deactivate_past_events).

End-time rule: the Event model has no end_time column (only `date` = start), so
an event is considered past when `date < now_la - GRACE_HOURS`. Event `date`
values are naive Los Angeles wall-clock times, so "now" is computed in
America/Los_Angeles (not UTC) to avoid the timezone skew that would otherwise
sweep in events that haven't started yet. If an end_time column is added later,
prefer it and fall back to start + GRACE_HOURS.

Idempotent: deleting IDs already absent from Pinecone (e.g. events that were
never embedded, or were cleaned on a prior run) is a no-op, so re-running the
cron is safe.
"""
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../.env"))

from db.session import SessionLocal
from app.models.event import Event
from agent.pinecone_client import delete_vectors

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

GRACE_HOURS = 3
# Event `date` values are stored as naive Los Angeles wall-clock times, so the
# cutoff is computed in LA local time. Requires the `tzdata` package on
# platforms without a system IANA database (e.g. Windows).
LOCAL_TZ = ZoneInfo("America/Los_Angeles")


def cleanup_past_event_vectors() -> int:
    """Delete Pinecone vectors for events whose start time + GRACE_HOURS has
    passed. Returns the number of past-event IDs submitted for deletion."""
    # Naive LA wall-clock 'now' to match the naive Supabase `date` column.
    now_la = datetime.now(LOCAL_TZ).replace(tzinfo=None)
    cutoff = now_la - timedelta(hours=GRACE_HOURS)
    db = SessionLocal()
    try:
        rows = db.query(Event.id).filter(Event.date < cutoff).all()
        ids = [str(r.id) for r in rows]
    finally:
        db.close()

    logger.info("Found %d events past cutoff %s LA (start + %dh)", len(ids), cutoff, GRACE_HOURS)
    if not ids:
        logger.info("No past events to clean up")
        return 0

    deleted = delete_vectors(ids)
    logger.info("Cleanup: %d past-event IDs submitted for Pinecone deletion", deleted)
    return deleted


def main() -> None:
    cleanup_past_event_vectors()
    logger.info("Cleanup complete")


if __name__ == "__main__":
    main()
