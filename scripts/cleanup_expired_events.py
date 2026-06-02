"""Mark past events inactive in the DB and remove their Pinecone vectors.

Usage:
  - Dry-run (default): python scripts/cleanup_expired_events.py
  - Non-interactive: python scripts/cleanup_expired_events.py --yes

DB: sets is_active=False for past events still marked active.
Pinecone: deletes vectors for ALL past events (active or already inactive),
          so expired events are not returned by semantic search.
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


def _past_event_query(db, cutoff_dt, *, active_only: bool):
    q = db.query(Event.id)
    if cutoff_dt is None:
        q = q.filter(Event.date < func.now())
    else:
        q = q.filter(Event.date < cutoff_dt)
    if active_only:
        q = q.filter(Event.is_active == True)  # noqa: E712
    return q


def find_past_active_event_ids(db, cutoff_dt=None):
    """Past events still marked active — candidates for is_active=False."""
    rows = _past_event_query(db, cutoff_dt, active_only=True).all()
    return [str(r.id) for r in rows]


def find_all_past_event_ids(db, cutoff_dt=None):
    """All past events — candidates for Pinecone vector deletion."""
    rows = _past_event_query(db, cutoff_dt, active_only=False).all()
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
    parser = argparse.ArgumentParser(
        description="Cleanup expired events: mark is_active=False and delete Pinecone vectors."
    )
    parser.add_argument("--yes", action="store_true", help="Perform changes (otherwise dry-run)")
    parser.add_argument(
        "--cutoff-iso",
        type=str,
        default=None,
        help="Optional ISO cutoff datetime. If omitted, DB now() is used.",
    )
    args = parser.parse_args()

    cutoff = None
    if args.cutoff_iso:
        parsed = datetime.fromisoformat(args.cutoff_iso)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        cutoff = parsed

    cutoff_label = cutoff.isoformat() if cutoff is not None else "DB now()"

    print("Connecting to DB...")
    db = SessionLocal()
    try:
        to_deactivate = find_past_active_event_ids(db, cutoff)
        to_delete_pc = find_all_past_event_ids(db, cutoff)

        print(f"Past events (cutoff={cutoff_label}):")
        print(f"  {len(to_deactivate)} still active in DB → will set is_active=False")
        print(f"  {len(to_delete_pc)} total past in DB → will delete Pinecone vectors")
        if to_delete_pc:
            print("Sample Pinecone delete IDs:", to_delete_pc[:5])

        if not to_deactivate and not to_delete_pc:
            print("Nothing to do.")
            return

        if not args.yes:
            print("Dry-run mode. No changes made. Re-run with --yes to apply.")
            return

        if to_deactivate:
            print("Marking newly expired events inactive in DB...")
            updated = mark_inactive(db, to_deactivate)
            print(f"  Marked {updated} events inactive in DB.")
    finally:
        db.close()

    if to_delete_pc:
        print("Deleting Pinecone vectors for all past events...")
        idx = _get_index()
        deleted = delete_pinecone_vectors(idx, to_delete_pc)
        print(f"  Deleted {deleted} Pinecone vectors.")
    print("Done.")


if __name__ == "__main__":
    main()
