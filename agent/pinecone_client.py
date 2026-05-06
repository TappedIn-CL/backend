import os
import time
import logging
from datetime import datetime
from pinecone import Pinecone
from dotenv import load_dotenv
from agent.embedding import embed_event
from agent.state import EventSchema

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
    return {
        "id": event["id"],
        "values": vector,
        "metadata": {
            "start_time_unix": start_time_unix,
            "latitude": event["latitude"],
            "longitude": event["longitude"],
            "price_min": event["price_min"],
            "price_max": event["price_max"],
            "city": event["city"],
            "category": event["category"],
            "tags": event["tags"],
            "title": event["title"],
            "venue_name": event["venue_name"],
        },
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


def search_events(
    vector: list[float], filters: dict, top_k: int = 20
) -> list[dict]:
    index = _get_index()
    kwargs: dict = {"vector": vector, "top_k": top_k, "include_metadata": True}
    if filters:
        kwargs["filter"] = filters
    response = index.query(**kwargs)
    return [
        {"id": m["id"], "score": m["score"], "metadata": m["metadata"]}
        for m in response["matches"]
    ]


def fetch_vectors(ids: list[str]) -> dict[str, list[float]]:
    """Batch-fetch event vectors by ID. IDs not found in the index are silently omitted."""
    if not ids:
        return {}
    index = _get_index()
    response = index.fetch(ids=ids)
    return {vec_id: vec.values for vec_id, vec in response.vectors.items()}
