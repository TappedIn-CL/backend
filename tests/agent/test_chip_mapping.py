"""
Tests for agent.chip_mapping — the single source of truth that turns the
frontend's selected vibe chips into embedding text + category filters.

These guard the bug that was fixed: parse_intent now actually consumes this
mapping, so the helpers must stay correct and the vocabulary must stay aligned
with taxonomy.py (the module self-validates at import, asserted here too).
"""

from agent.chip_mapping import (
    CHIPS,
    CHIP_MAPPING,
    merge_chips_into_query,
    chips_to_categories,
)
from agent.taxonomy import CATEGORIES, VIBE_TAGS


# ── merge_chips_into_query ──────────────────────────────────────────────────

def test_merge_appends_semantic_phrases():
    out = merge_chips_into_query("live shows", ["Music"])
    assert out == "live shows music live performance concert"


def test_merge_multiple_chips_in_order():
    out = merge_chips_into_query("tonight", ["Music", "Cozy"])
    assert "music live performance concert" in out
    assert "cozy warm intimate relaxed" in out


def test_merge_no_chips_returns_query_unchanged():
    assert merge_chips_into_query("jazz", []) == "jazz"


def test_merge_ignores_unmapped_chips():
    # "Happening Now" is a separate feature with no mapping — must be a no-op.
    assert merge_chips_into_query("jazz", ["Happening Now"]) == "jazz"


# ── chips_to_categories ─────────────────────────────────────────────────────

def test_chips_to_categories_extracts_and_dedupes():
    assert chips_to_categories(["Music", "Foodie"]) == ["Music", "Food & Drink"]


def test_chips_to_categories_vibe_only_chip_is_empty():
    # "Chill"/"Cozy" carry vibes but no category.
    assert chips_to_categories(["Chill", "Cozy"]) == []


def test_chips_to_categories_dedupes_preserving_order():
    assert chips_to_categories(["Music", "Music"]) == ["Music"]


def test_chips_to_categories_ignores_unmapped():
    assert chips_to_categories(["Happening Now", "Sports"]) == ["Sports"]


# ── the previously-missing "Cozy" chip ──────────────────────────────────────

def test_cozy_chip_is_now_mapped():
    assert "Cozy" in CHIP_MAPPING
    assert "Cozy" in CHIPS
    assert merge_chips_into_query("x", ["Cozy"]) != "x"  # actually does something


# ── vocabulary invariants (mirror the module's import-time validation) ──────

def test_every_chip_is_mapped():
    assert set(CHIPS) == set(CHIP_MAPPING.keys())


def test_all_referenced_categories_and_vibes_are_valid_taxonomy():
    valid_cats, valid_vibes = set(CATEGORIES), set(VIBE_TAGS)
    for chip, m in CHIP_MAPPING.items():
        assert set(m["categories"]) <= valid_cats, f"{chip} references unknown category"
        assert set(m["vibe_tags"]) <= valid_vibes, f"{chip} references unknown vibe_tag"
        assert m["semantic_phrase"], f"{chip} has empty semantic_phrase"
