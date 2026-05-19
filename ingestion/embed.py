import logging
from agent.pinecone_client import upsert_events
from agent.state import EventSchema

logger = logging.getLogger(__name__)

REQUIRED_FIELDS = {"id", "title", "description", "category", "tags", "vibe_tags"}


def embed_and_upsert(events: list[EventSchema]) -> int:
    if not events:
        return 0

    valid = []
    for event in events:
        missing = [f for f in REQUIRED_FIELDS if not event.get(f)]
        if missing:
            logger.warning(
                "Skipping event %s — missing or null fields: %s",
                event.get("id") or event.get("title") or "unknown",
                missing,
            )
        else:
            valid.append(event)

    return upsert_events(valid)
