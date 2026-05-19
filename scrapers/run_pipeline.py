"""
End-to-end ingestion pipeline.

  Stage 1: SCRAPE   — write raw events to Supabase (current scraper behavior)
  Stage 2: ENRICH   — LLM-fill category/tags/vibe_tags on rows that lack them
  Stage 3: EMBED    — upsert (vector, sparse metadata) into Pinecone

Idempotency:
  - Enrich selects rows WHERE vibe_tags IS NULL.
  - Embed skips events already present in Pinecone (fetch_vectors check).

So re-running the cron is safe and cheap — only new/unprocessed work hits the LLM
and OpenAI embedding APIs.
"""
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import logging
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../.env"))

from db.session import SessionLocal
from app.models.event import Event
from app.utils.event_utils import event_to_hydrated
from ingestion.enrichment import enrich_event
from ingestion.embed import embed_and_upsert
from agent.pinecone_client import fetch_vectors
from scrapers.uncoverla import run_scrape

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def stage_scrape() -> int:
    logger.info("=== Stage 1: SCRAPE ===")
    return run_scrape()


def stage_enrich() -> int:
    """Run LLM enrichment on events that haven't been classified yet."""
    logger.info("=== Stage 2: ENRICH ===")
    db = SessionLocal()
    enriched_count = 0
    try:
        unenriched = db.query(Event).filter(Event.vibe_tags.is_(None)).all()
        logger.info("Found %d events lacking vibe_tags", len(unenriched))

        for event in unenriched:
            event_dict = {
                "id": str(event.id),
                "title": event.title or "",
                "description": event.description or "",
                "venue_name": event.location or "",
            }
            try:
                result = enrich_event(event_dict)
                event.category = result.get("category")
                event.special_tags = ",".join(result.get("tags", []))
                event.vibe_tags = ",".join(result.get("vibe_tags", []))
                enriched_count += 1
                logger.info(
                    "  ✓ %s → category=%s tags=%s vibes=%s",
                    (event.title or "")[:50],
                    event.category,
                    event.special_tags,
                    event.vibe_tags,
                )
            except Exception as e:
                logger.warning("  ✗ enrichment failed for %s: %s", event.title, e)

        db.commit()
    finally:
        db.close()
    logger.info("Enriched %d events", enriched_count)
    return enriched_count


def stage_embed() -> int:
    """Embed enriched rows and upsert to Pinecone, skipping ones already indexed."""
    logger.info("=== Stage 3: EMBED + UPSERT ===")
    db = SessionLocal()
    try:
        enriched = db.query(Event).filter(Event.vibe_tags.isnot(None)).all()
        if not enriched:
            logger.info("No enriched events found")
            return 0

        all_ids = [str(e.id) for e in enriched]
        existing = fetch_vectors(all_ids)
        to_index = [e for e in enriched if str(e.id) not in existing]
        logger.info(
            "Enriched=%d, already in Pinecone=%d, to index=%d",
            len(enriched),
            len(existing),
            len(to_index),
        )

        if not to_index:
            return 0

        event_dicts = []
        for db_event in to_index:
            hydrated = event_to_hydrated(db_event)
            event_dicts.append(hydrated.model_dump(mode="json"))

        n = embed_and_upsert(event_dicts)
        logger.info("Upserted %d events to Pinecone", n)
        return n
    finally:
        db.close()


def main() -> None:
    stage_scrape()
    stage_enrich()
    stage_embed()
    logger.info("Pipeline complete")


if __name__ == "__main__":
    main()
