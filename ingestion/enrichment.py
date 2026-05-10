"""
LLM enrichment for scraped events.

Takes a raw scraped event dict (title, description, venue, etc.) and returns
the same dict augmented with semantic fields that the embedding pipeline needs:
  - category    (one of taxonomy.CATEGORIES)
  - tags        (subset of taxonomy.SPECIAL_TAGS)
  - vibe_tags   (subset of taxonomy.VIBE_TAGS)

Hard-filter fields (price, date, location) are NOT inferred here — those should
already be present from the scrape. This module only fills semantic fields.

Runs once per event during ingestion. Plain function call to OpenAI — no
LangGraph involved (LangGraph is reserved for query-time orchestration).
"""

import json
import logging
import os
from typing import Any

from openai import OpenAI
from dotenv import load_dotenv

from agent.taxonomy import CATEGORIES, SPECIAL_TAGS, VIBE_TAGS

load_dotenv()

logger = logging.getLogger(__name__)

ENRICHMENT_MODEL = "gpt-4o-mini"
ENRICHMENT_TEMPERATURE = 0.0

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _client


SYSTEM_PROMPT = f"""\
You are an event taxonomy extractor for TappedIn, an LA event discovery platform.

Given a scraped event with title, description, and venue, classify it into
the canonical TappedIn taxonomy.

Output STRICT JSON with exactly these three keys:

  category: exactly one of {CATEGORIES}
  tags: subset (zero or more) of {SPECIAL_TAGS}
  vibe_tags: subset (one or more, max 3) of {VIBE_TAGS}

Definitions:
  - category: the primary type of the event. Pick the single best match.
  - tags: objective logistical descriptors. Include "outdoor" only if the event
    is clearly held outside (rooftops, parks, patios). Include "21+" only if
    the description says so or it is held at a venue that is 21+ by default
    (bar, brewery, club). Include "free" only if there is no admission cost.
    Include "pop-up" if the event is a one-off or limited-run popup format.
  - vibe_tags: the subjective feel of the event. Pick the 1-3 most fitting.
    "chill" = relaxed, low-stakes, mellow.
    "energetic" / "hyped" = loud, high-tempo, party-like.
    "intimate" = small venue, romantic-friendly, low capacity.
    "social" = group-friendly, mingling-oriented.
    "creative" = art, craft, DIY, expression-focused.
    "educational" = workshops, talks, classes.
    "adventurous" = active, outdoorsy, novel experience.

Rules:
  - Output strict JSON only. No prose, no markdown fences, no comments.
  - Use exactly the spellings above (case-sensitive).
  - If the event is too ambiguous to classify confidently, default to:
    category=Other, tags=[], vibe_tags=["social"].
"""


def _build_user_prompt(event: dict[str, Any]) -> str:
    title = event.get("title", "").strip() or "(no title)"
    description = event.get("description", "").strip() or "(no description)"
    venue = event.get("venue_name", "").strip() or "(no venue)"
    return (
        f"Title: {title}\n"
        f"Venue: {venue}\n"
        f"Description: {description}"
    )


def _validate_enrichment(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Coerce LLM output to canonical vocabulary. Drops anything not in the enum
    so a hallucinated tag never reaches Pinecone metadata.
    """
    category = payload.get("category")
    if category not in CATEGORIES:
        # "Other" is the explicit catch-all bucket — using "Networking" as a
        # fallback would silently pollute that category with unclassifiable
        # events and skew searches for actual networking events.
        logger.warning("LLM returned invalid category %r — defaulting to Other", category)
        category = "Other"

    raw_tags = payload.get("tags") or []
    tags = [t for t in raw_tags if t in SPECIAL_TAGS]

    raw_vibes = payload.get("vibe_tags") or []
    vibe_tags = [v for v in raw_vibes if v in VIBE_TAGS]
    if not vibe_tags:
        vibe_tags = ["social"]
    vibe_tags = vibe_tags[:3]

    return {"category": category, "tags": tags, "vibe_tags": vibe_tags}


def enrich_event(event: dict[str, Any]) -> dict[str, Any]:
    """
    Calls the LLM to classify a single scraped event. Returns a NEW dict
    with category/tags/vibe_tags merged in. Does not mutate the input.

    Raises on transport errors so the caller can retry. Returns sane fallback
    values on malformed LLM output.
    """
    response = _get_client().chat.completions.create(
        model=ENRICHMENT_MODEL,
        temperature=ENRICHMENT_TEMPERATURE,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(event)},
        ],
    )
    raw = response.choices[0].message.content or "{}"
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("LLM returned non-JSON for event %s — falling back", event.get("id"))
        payload = {}

    enrichment = _validate_enrichment(payload)
    return {**event, **enrichment}


def enrich_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Batch helper. Continues on per-event failure rather than aborting the run."""
    enriched: list[dict[str, Any]] = []
    for event in events:
        try:
            enriched.append(enrich_event(event))
        except Exception as exc:
            logger.error(
                "Enrichment failed for event %s: %s",
                event.get("id") or event.get("title") or "unknown",
                exc,
            )
    return enriched
