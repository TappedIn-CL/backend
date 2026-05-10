"""
Canonical enum vocabulary for TappedIn's event taxonomy.

Both the ingestion enrichment prompt and the query intent parser must reference
the SAME enum lists, or the metadata-filter contract between them breaks.
If ingestion tags an event with vibe_tags=["chill"] but the query parser
emits vibe_tags_required=["mellow"], Pinecone's $in filter matches zero events.

When you change a list here, you must:
  1. Update the LLM prompts that reference it (enrichment.py, parse_intent in nodes.py).
  2. Re-run ingestion to re-tag historical events with the new vocabulary.
"""

CATEGORIES: list[str] = [
    "Music",
    "Food & Drink",
    "Arts",
    "Nightlife",
    "Comedy",
    "Wellness",
    "Networking",
    "Sports",
    "Family",
    "Fashion",
    "Other",
]

VIBE_TAGS: list[str] = [
    "chill",
    "energetic",
    "intimate",
    "social",
    "creative",
    "hyped",
    "educational",
    "adventurous",
]

SPECIAL_TAGS: list[str] = [
    "outdoor",
    "indoor",
    "21+",
    "family-friendly",
    "limited-spots",
    "pop-up",
    "free-perks",
    "free",
]
