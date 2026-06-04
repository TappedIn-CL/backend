import os
import time
import logging
from datetime import datetime
from typing import Literal
from pinecone import Pinecone
from dotenv import load_dotenv
from agent.embedding import embed_event
from agent.state import EventSchema

# Mirrors app/utils/event_utils.DEFAULT_EVENT_DURATION_HOURS and
# agent/nodes.DEFAULT_EVENT_DURATION_HOURS so an event's effective end time
# is computed identically at ingest, query, and hydrate.
DEFAULT_EVENT_DURATION_HOURS = 3
HAPPENING_NOW_LOOKBACK_SECONDS = 24 * 3600

TimeMode = Literal["upcoming", "happening_now"]

load_dotenv()

logger = logging.getLogger(__name__)

_pc: Pinecone | None = None
_index = None


def _get_index():
    global _pc, _index
    if _index is None:
        _pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
        _index = _pc.Index(os.getenv("PINECONE_INDEX", "tappedin-events"))
    return _index


def _build_record(event: EventSchema, vector: list[float]) -> dict:
    start_time_unix = int(
        datetime.fromisoformat(event["start_time"].replace("Z", "+00:00")).timestamp()
    )
    end_iso = event.get("end_time")
    if end_iso:
        end_time_unix = int(
            datetime.fromisoformat(end_iso.replace("Z", "+00:00")).timestamp()
        )
    else:
        end_time_unix = start_time_unix + DEFAULT_EVENT_DURATION_HOURS * 3600
    metadata = {
        "start_time_unix": start_time_unix,
        "end_time_unix": end_time_unix,
        "latitude": event["latitude"],
        "longitude": event["longitude"],
        "price_min": event["price_min"],
        "price_max": event["price_max"],
        "city": event["city"],
        "category": event["category"],
        "tags": event["tags"],
        "title": event["title"],
        "venue_name": event["venue_name"],
    }
    # Pinecone rejects null metadata; drop any None-valued fields.
    metadata = {k: v for k, v in metadata.items() if v is not None}
    return {
        "id": event["id"],
        "values": vector,
        "metadata": metadata,
    }


def _upsert_batch_with_retry(index, batch: list[dict]) -> bool:
    for attempt in range(4):
        try:
            index.upsert(vectors=batch)
            return True
        except Exception as e:
            if attempt < 3:
                time.sleep(2 ** attempt)
            else:
                logger.error("Batch upsert failed after 4 attempts: %s", e)
    return False


def upsert_events(events: list[EventSchema]) -> int:
    index = _get_index()
    records = []
    for event in events:
        try:
            vector = embed_event(event)
            records.append(_build_record(event, vector))
        except Exception as e:
            logger.warning("Failed to embed event %s: %s", event.get("id"), e)

    total = 0
    for i in range(0, len(records), 100):
        batch = records[i : i + 100]
        if _upsert_batch_with_retry(index, batch):
            total += len(batch)
    return total


def upcoming_only_filter(extra: dict | None = None) -> dict:
    """Restrict Pinecone queries to events that have not started yet."""
    f: dict = {"start_time_unix": {"$gte": int(time.time())}}
    if extra:
        f.update(extra)
    return f


def happening_now_filter(extra: dict | None = None) -> dict:
    """Restrict Pinecone queries to events likely in progress right now.

    Uses a lenient start_time_unix window (last 24h → now) rather than checking
    end_time_unix directly. This is intentional: legacy vectors don't have
    end_time_unix in metadata yet, and Pinecone treats missing fields as
    non-matching, so a strict end_time check would silently drop most of the
    index. The hydrate_events node re-applies a precise start <= now <=
    effective_end_time filter using Allen's effective_end_time helper against
    Supabase, so this window is just the cheap vector-layer pre-filter.
    """
    now = int(time.time())
    f: dict = {"start_time_unix": {"$gte": now - HAPPENING_NOW_LOOKBACK_SECONDS, "$lte": now}}
    if extra:
        f.update(extra)
    return f


def search_events(
    vector: list[float],
    filters: dict,
    top_k: int = 20,
    time_mode: TimeMode = "upcoming",
) -> list[dict]:
    index = _get_index()
    builder = happening_now_filter if time_mode == "happening_now" else upcoming_only_filter
    kwargs: dict = {
        "vector": vector,
        "top_k": top_k,
        "include_metadata": True,
        "filter": builder(filters or None),
    }
    response = index.query(**kwargs)
    return [
        {"id": m["id"], "score": m["score"], "metadata": m["metadata"]}
        for m in response["matches"]
    ]


_FETCH_BATCH_SIZE = 100


_DELETE_BATCH_SIZE = 1000


def delete_vectors(ids: list[str]) -> int:
    """Delete vectors by ID from Pinecone. Missing IDs are no-ops (idempotent).

    Used by the daily cleanup job to evict vectors for past events. The Supabase
    rows are kept; only the search-index vectors are removed. Returns the count
    of IDs submitted for deletion. Pinecone's delete accepts up to 1000 IDs per
    call, so we chunk to stay within that limit.
    """
    if not ids:
        return 0
    index = _get_index()
    deleted = 0
    for i in range(0, len(ids), _DELETE_BATCH_SIZE):
        batch = ids[i : i + _DELETE_BATCH_SIZE]
        try:
            index.delete(ids=batch)
            deleted += len(batch)
        except Exception as e:
            logger.error("delete_vectors batch %d-%d failed: %s", i, i + len(batch), e)
    return deleted


def fetch_vectors(ids: list[str]) -> dict[str, list[float]]:
    """Batch-fetch event vectors by ID. IDs not found in the index are silently omitted.

    Pinecone's fetch endpoint uses GET with IDs as query params, so large ID
    lists cause 414 Request-URI Too Large. We chunk into batches of
    _FETCH_BATCH_SIZE to stay well within URL length limits.
    """
    if not ids:
        return {}
    index = _get_index()
    result: dict[str, list[float]] = {}
    for i in range(0, len(ids), _FETCH_BATCH_SIZE):
        batch = ids[i : i + _FETCH_BATCH_SIZE]
        try:
            response = index.fetch(ids=batch)
            result.update({vec_id: vec.values for vec_id, vec in response.vectors.items()})
        except Exception as e:
            logger.error("fetch_vectors batch %d-%d failed: %s", i, i + len(batch), e)
    return result
