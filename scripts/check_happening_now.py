"""Ground-truth check: list events that are currently in progress per the same
end_time rules the agent uses (Allen's effective_end_time: stored end_time, or
start + DEFAULT_EVENT_DURATION_HOURS if NULL).

If this prints 0 events and Happening Now returns 0 events, the backend is
behaving correctly — nothing is actually happening right now. If this prints
N > 0 events but Happening Now returns 0, then the agent is dropping events
that should be visible (file a bug).

Also cross-checks against Pinecone: prints how many of the in-progress events
have a vector in the index, so you can spot ingest gaps.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

# Ensure backend/ (the repo root for app/, agent/) is on the path even when
# running this script directly from a subdirectory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Import these BEFORE creating the engine so models register with Base.
from app.models.event import Event  # noqa: F401
from app.utils.event_utils import DEFAULT_EVENT_DURATION_HOURS, effective_end_time
from agent.pinecone_client import _get_index

load_dotenv()


def main() -> None:
    db_url = os.environ["DATABASE_URL"]
    engine = create_engine(db_url)
    Session = sessionmaker(bind=engine)
    db = Session()

    now = datetime.now()  # naive LA wall-clock — matches how events are stored
    print(f"Now (local naive): {now.isoformat()}")
    print(f"Default duration: {DEFAULT_EVENT_DURATION_HOURS}h\n")

    # Pull all active events with a start date — small enough to filter in Python
    # so we can use the same effective_end_time helper the agent uses.
    events = (
        db.query(Event)
        .filter(Event.is_active == True)  # noqa: E712
        .filter(Event.date.isnot(None))
        .filter(Event.date <= now)  # already started
        .all()
    )

    in_progress = []
    for e in events:
        end = effective_end_time(e)
        if end is None:
            continue
        if e.date <= now <= end:
            in_progress.append((e, end))

    print(f"Active events that started already: {len(events)}")
    print(f"Active events currently in progress: {len(in_progress)}\n")

    if not in_progress:
        print("→ Happening Now returning 0 results is CORRECT.")
        print("  Nothing is in progress per the start <= now <= end rule.\n")
        return

    # Cross-check Pinecone presence for each in-progress event.
    print(f"{'='*80}")
    print(f"{'Title':<50} {'Start':<20} {'End':<20} {'In Pinecone?'}")
    print(f"{'='*80}")
    try:
        index = _get_index()
        ids = [str(e.id) for e, _ in in_progress]
        fetched = index.fetch(ids=ids)
        in_pinecone = set(fetched.vectors.keys())
    except Exception as exc:
        print(f"(Pinecone fetch failed: {exc})")
        in_pinecone = set()

    missing_from_pinecone = 0
    for event, end in in_progress[:30]:
        present = "yes" if str(event.id) in in_pinecone else "NO"
        if present == "NO":
            missing_from_pinecone += 1
        title = (event.title or "")[:48]
        print(f"{title:<50} {event.date.isoformat():<20} {end.isoformat():<20} {present}")

    if len(in_progress) > 30:
        print(f"... and {len(in_progress) - 30} more")

    print()
    if missing_from_pinecone:
        print(
            f"WARNING: {missing_from_pinecone}/{len(in_progress)} in-progress events "
            "missing from Pinecone. These won't surface in Happening Now even though "
            "they're in Supabase — re-run the ingest pipeline."
        )
    else:
        print(
            f"All {len(in_progress)} in-progress events are in Pinecone. If Happening "
            "Now still returns 0, check the lenient 24h window — events that started "
            "more than 24h ago won't even reach the precision filter."
        )


if __name__ == "__main__":
    main()
