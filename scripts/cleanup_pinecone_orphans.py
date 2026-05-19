"""Delete Pinecone vectors whose IDs don't exist in Supabase.

These orphans accumulate when:
  - Supabase rows get deleted but their Pinecone vectors don't
  - The scraper inserts new rows under different UUIDs for the same logical event
  - Old test/mock IDs (e.g. evt-001) never had matching Supabase rows

Run with: PYTHONIOENCODING=utf-8 python scripts/cleanup_pinecone_orphans.py
"""
import os, sys
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(override=True)

import uuid
from db.session import SessionLocal
from app.models.event import Event
from agent.pinecone_client import _get_index

print("Fetching all Supabase event IDs...")
db = SessionLocal()
try:
    supabase_ids = {str(e.id) for e in db.query(Event.id).all()}
    print(f"  Supabase has {len(supabase_ids)} events")
finally:
    db.close()

idx = _get_index()
stats = idx.describe_index_stats()
pc_total = stats["total_vector_count"]
print(f"\nPinecone has {pc_total} vectors")

# Pinecone doesn't have a simple list-all API for old SDK versions.
# Best portable way: query with a near-zero vector at high top_k.
# This works because all 1536-dim vectors have non-zero cosine similarity to a tiny vector.
print("\nPaging through Pinecone IDs (querying in batches)...")
all_pc_ids: set[str] = set()
# Single query with top_k = total_vector_count gets us everything.
r = idx.query(vector=[0.001] * 1536, top_k=max(pc_total, 1), include_metadata=False)
for m in r["matches"]:
    all_pc_ids.add(m["id"])
print(f"  Retrieved {len(all_pc_ids)} Pinecone IDs")

# Identify orphans
orphans = []
for pc_id in all_pc_ids:
    # Non-UUID IDs (legacy mocks) are always orphans
    try:
        uuid.UUID(pc_id)
        is_uuid = True
    except ValueError:
        is_uuid = False
    if not is_uuid or pc_id not in supabase_ids:
        orphans.append(pc_id)

print(f"\n{len(orphans)} orphan vectors found (in Pinecone but NOT in Supabase)")

if not orphans:
    print("Nothing to clean up.")
    sys.exit(0)

# Confirm before delete
print(f"\nWill delete {len(orphans)} vectors from Pinecone.")
print("Sample orphan IDs:", orphans[:5])

resp = input("\nProceed? [y/N]: ").strip().lower()
if resp != "y":
    print("Aborted.")
    sys.exit(0)

# Delete in batches of 100 (Pinecone API limit)
deleted = 0
for i in range(0, len(orphans), 100):
    batch = orphans[i : i + 100]
    idx.delete(ids=batch)
    deleted += len(batch)
    print(f"  Deleted {deleted}/{len(orphans)}")

print(f"\nDone. Removed {deleted} orphans.")
print(f"Pinecone now has {pc_total - deleted} valid vectors (was {pc_total}).")
