import logging
from agent.pinecone_client import upsert_events
from agent.state import EventSchema

logger = logging.getLogger(__name__)

# `tags` (special_tags) is normal-empty for most events — the LLM correctly
# returns [] when nothing qualifies for free/21+/outdoor/pop-up. It only adds
# trivial enum strings to the embedding text and is Pinecone-metadata-
# filterable separately, so an empty value isn't reason to drop the event.
# `description` STAYS required: it's the bulk of semantic content in the
# embedding text AND the primary input to vibe_tags derivation in enrichment.
# Letting events through without it would pollute the index with weak,
# guessed-vibe embeddings — better to fix the upstream scraper.
REQUIRED_FIELDS = {"id", "title", "description", "category", "vibe_tags"}


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
