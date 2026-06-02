"""Mark past events inactive in the DB and remove their Pinecone vectors.

Usage:
  - Dry-run (default): python scripts/cleanup_expired_events.py
  - Non-interactive: python scripts/cleanup_expired_events.py --yes

The script is intentionally conservative: it flips `is_active` in the DB
first (authoritative), then deletes vectors from Pinecone in batches.
"""
import os
import sys
import time
import argparse
from datetime import datetime, timezone
from sqlalchemy import func

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(override=True)

from db.session import SessionLocal
from app.models.event import Event
from agent.pinecone_client import _get_index


def chunked(iterable, size):
    for i in range(0, len(iterable), size):
        yield iterable[i : i + size]


def find_expired_event_ids(db, cutoff_dt=None):
    # If no cutoff provided, use DB-side now() to avoid timezone drift between
    # app and DB. If cutoff_dt is provided (ISO string parsed), compare against it.
    if cutoff_dt is None:
        rows = db.query(Event.id).filter(Event.date < func.now(), Event.is_active == True).all()
    else:
        rows = db.query(Event.id).filter(Event.date < cutoff_dt, Event.is_active == True).all()
    return [str(r.id) for r in rows]


def mark_inactive(db, ids):
    if not ids:
        return 0
    updated = db.query(Event).filter(Event.id.in_(ids)).update({"is_active": False}, synchronize_session=False)
    db.commit()
    return updated


def delete_pinecone_vectors(index, ids):
    deleted = 0
    for batch in chunked(ids, 100):
        # simple retry logic per batch
        for attempt in range(4):
            try:
                index.delete(ids=batch)
                deleted += len(batch)
                break
            except Exception as e:
                if attempt < 3:
                    time.sleep(2 ** attempt)
                else:
                    print(f"Failed to delete batch after retries: {e}")
    return deleted


def main():
    parser = argparse.ArgumentParser(description="Cleanup expired events: mark is_active=False and delete Pinecone vectors.")
    parser.add_argument("--yes", action="store_true", help="Perform changes (otherwise dry-run)")
    parser.add_argument("--cutoff-iso", type=str, default=None, help="Optional ISO cutoff datetime. If omitted, DB now() is used.")
    args = parser.parse_args()

    cutoff = None
    if args.cutoff_iso:
        # parse ISO; treat naive datetimes as UTC
        parsed = datetime.fromisoformat(args.cutoff_iso)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        cutoff = parsed

    print("Connecting to DB...")
    db = SessionLocal()
    try:
        ids = find_expired_event_ids(db, cutoff)
        print(f"Found {len(ids)} expired active events (cutoff={cutoff.isoformat()})")
        if ids:
            print("Sample IDs:", ids[:5])
        else:
            print("Nothing to do.")
            return

        if not args.yes:
            print("Dry-run mode. No changes made. Re-run with --yes to apply.")
            return

        print("Marking events inactive in DB...")
        updated = mark_inactive(db, ids)
        print(f"  Marked {updated} events inactive in DB.")
    finally:
        db.close()

    # Delete Pinecone vectors
    print("Deleting Pinecone vectors...")
    idx = _get_index()
    deleted = delete_pinecone_vectors(idx, ids)
    print(f"  Deleted {deleted} Pinecone vectors.")
    print("Done.")


if __name__ == "__main__":
    main()
