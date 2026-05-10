"""
Chip mapping — single source of truth for the 12 frontend chips.

Each chip maps to:
  - categories: taxonomy categories the chip implies (used by parse_intent for filters)
  - vibe_tags: taxonomy vibe_tags the chip implies (NOT a Pinecone hard filter —
    vibe_tags are not stored in Pinecone metadata; they contribute to semantic_phrase
    so the embedding picks up the mood signal instead)
  - semantic_phrase: short text appended to the user query before embedding

Frontend imports the same contract via the JSON dumped by `export_to_json()`
or `python -m agent.chip_mapping`.
"""

import json
from typing import TypedDict

from agent.taxonomy import CATEGORIES, VIBE_TAGS


class ChipMapping(TypedDict):
    categories: list[str]
    vibe_tags: list[str]
    semantic_phrase: str


CHIPS: list[str] = [
    "Chill",
    "Hype",
    "Creative",
    "Foodie",
    "Adventurous",
    "Nightlife",
    "Comedy",
    "Music",
    "Date Night",
    "With Friends",
    "Wellness",
    "Sports",
]


CHIP_MAPPING: dict[str, ChipMapping] = {
    "Chill": {
        "categories": [],
        "vibe_tags": ["chill"],
        "semantic_phrase": "chill relaxed laid-back",
    },
    "Hype": {
        "categories": [],
        "vibe_tags": ["hyped", "energetic"],
        "semantic_phrase": "hype high-energy",
    },
    "Creative": {
        "categories": ["Arts"],
        "vibe_tags": ["creative"],
        "semantic_phrase": "creative artistic",
    },
    "Foodie": {
        "categories": ["Food & Drink"],
        "vibe_tags": ["social"],
        "semantic_phrase": "foodie dining culinary",
    },
    "Adventurous": {
        "categories": [],
        "vibe_tags": ["adventurous"],
        "semantic_phrase": "adventurous outdoors exciting",
    },
    "Nightlife": {
        "categories": ["Nightlife"],
        "vibe_tags": ["energetic"],
        "semantic_phrase": "nightlife bars clubs late-night",
    },
    "Comedy": {
        "categories": ["Comedy"],
        "vibe_tags": ["social", "energetic"],
        "semantic_phrase": "comedy stand-up funny",
    },
    "Music": {
        "categories": ["Music"],
        "vibe_tags": ["social"],
        "semantic_phrase": "music live performance concert",
    },
    "Date Night": {
        "categories": [],
        "vibe_tags": ["intimate"],
        "semantic_phrase": "date night romantic intimate",
    },
    "With Friends": {
        "categories": [],
        "vibe_tags": ["social"],
        "semantic_phrase": "with friends group hangout social",
    },
    "Wellness": {
        "categories": ["Wellness"],
        "vibe_tags": ["chill"],
        "semantic_phrase": "wellness self-care mindful relaxing",
    },
    "Sports": {
        "categories": ["Sports"],
        "vibe_tags": ["hyped", "energetic"],
        "semantic_phrase": "sports athletic active competitive",
    },
}


# Validate at import time: every taxonomy value referenced in CHIP_MAPPING
# must exist in taxonomy.py. Catches drift before it reaches Pinecone.
def _validate_mappings() -> None:
    valid_categories = set(CATEGORIES)
    valid_vibes = set(VIBE_TAGS)
    for chip, mapping in CHIP_MAPPING.items():
        for cat in mapping["categories"]:
            if cat not in valid_categories:
                raise ValueError(f"Chip '{chip}' references unknown category '{cat}'")
        for vibe in mapping["vibe_tags"]:
            if vibe not in valid_vibes:
                raise ValueError(f"Chip '{chip}' references unknown vibe_tag '{vibe}'")
    missing = set(CHIPS) - set(CHIP_MAPPING.keys())
    if missing:
        raise ValueError(f"CHIPS list contains unmapped entries: {missing}")


_validate_mappings()


def merge_chips_into_query(query: str, chips: list[str]) -> str:
    """
    Append chip semantic phrases to the user query before embedding.

    Used by parse_intent to enrich the embedding signal — vibes/moods land
    in the embedding rather than as Pinecone hard filters that would silently
    match zero events.
    """
    phrases = [
        CHIP_MAPPING[chip]["semantic_phrase"]
        for chip in chips
        if chip in CHIP_MAPPING
    ]
    if not phrases:
        return query
    return f"{query} {' '.join(phrases)}".strip()


def chips_to_categories(chips: list[str]) -> list[str]:
    """Unique taxonomy categories implied by the selected chips, in order."""
    seen: set[str] = set()
    result: list[str] = []
    for chip in chips:
        for cat in CHIP_MAPPING.get(chip, {}).get("categories", []):
            if cat not in seen:
                seen.add(cat)
                result.append(cat)
    return result


def export_to_json() -> dict:
    """JSON contract for the frontend. Mirror this shape in TypeScript."""
    return {
        "chips": CHIPS,
        "mapping": {chip: dict(value) for chip, value in CHIP_MAPPING.items()},
    }


if __name__ == "__main__":
    print(json.dumps(export_to_json(), indent=2))
