Cleanup expired events
======================

This folder contains `cleanup_expired_events.py`, a small maintenance script that:

- Finds events where `date < now()` and `is_active = true`.
- Marks those events `is_active = false` in the DB.
- Deletes the corresponding Pinecone vectors in batches.

Local dry-run example:

```bash
PYTHONPATH=. DATABASE_URL="<your-db>" PINECONE_API_KEY="<key>" PINECONE_INDEX="<index>" python scripts/cleanup_expired_events.py
```

To actually apply changes (non-interactive):

```bash
PYTHONPATH=. DATABASE_URL="<your-db>" PINECONE_API_KEY="<key>" PINECONE_INDEX="<index>" python scripts/cleanup_expired_events.py --yes
```
