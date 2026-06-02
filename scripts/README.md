Cleanup expired events
======================

This folder contains `cleanup_expired_events.py`, a small maintenance script that:

- Finds events where `date < now()` and `is_active = true`, marks them inactive in the DB.
- Deletes Pinecone vectors for **all** past events (`date < now()`), including ones already inactive — so stale vectors left by scrapers are removed.
- Agent search also filters Pinecone with `start_time_unix >= now` so only upcoming events are retrieved.

Local dry-run example:

```bash
PYTHONPATH=. DATABASE_URL="<your-db>" PINECONE_API_KEY="<key>" PINECONE_INDEX="<index>" python scripts/cleanup_expired_events.py
```

To actually apply changes (non-interactive):

```bash
PYTHONPATH=. DATABASE_URL="<your-db>" PINECONE_API_KEY="<key>" PINECONE_INDEX="<index>" python scripts/cleanup_expired_events.py --yes
```
