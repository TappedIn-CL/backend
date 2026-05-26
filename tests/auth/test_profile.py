"""Tests for auth/profile.py — price parsing and profile loader shape."""
from types import SimpleNamespace

import pytest

from auth.profile import _build_profile, _parse_price_max


# ── _parse_price_max ───────────────────────────────────────────────────────

@pytest.mark.parametrize("inp", [None, "", "   "])
def test_parse_price_max_none_or_blank(inp):
    assert _parse_price_max(inp) is None


@pytest.mark.parametrize("inp", ["Free", "FREE", "free", "$0", "0"])
def test_parse_price_max_free_inputs_return_zero(inp):
    assert _parse_price_max(inp) == 0.0


def test_parse_price_max_range_returns_upper_bound():
    assert _parse_price_max("$0-$20") == 20.0


def test_parse_price_max_under_pattern_returns_number():
    assert _parse_price_max("Under 50") == 50.0


def test_parse_price_max_handles_decimal():
    assert _parse_price_max("Up to $19.99") == pytest.approx(19.99)


def test_parse_price_max_no_digits_returns_none():
    assert _parse_price_max("$$") is None
    assert _parse_price_max("abc") is None
    assert _parse_price_max("$$$") is None


def test_parse_price_max_picks_largest_number():
    # multiple numbers → take the upper bound
    assert _parse_price_max("from $10 to $35, average $20") == 35.0


# ── _build_profile ─────────────────────────────────────────────────────────

def _mock_user(**overrides):
    base = dict(
        interests=None,
        vibes=None,
        price_range=None,
        neighborhood=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_build_profile_returns_all_expected_keys():
    user = _mock_user()
    profile = _build_profile(user, [])
    assert set(profile.keys()) == {
        "interests",
        "vibes",
        "favorited_tags",
        "favorited_event_ids",
        "price_max",
        "neighborhood",
    }


def test_build_profile_defaults_none_arrays_to_empty_list():
    user = _mock_user(interests=None, vibes=None)
    profile = _build_profile(user, [])
    assert profile["interests"] == []
    assert profile["vibes"] == []
    assert profile["favorited_tags"] == []
    assert profile["favorited_event_ids"] == []


def test_build_profile_passes_through_interests_and_vibes():
    user = _mock_user(interests=["jazz", "art"], vibes=["chill"])
    profile = _build_profile(user, ["fav-1", "fav-2"])
    assert profile["interests"] == ["jazz", "art"]
    assert profile["vibes"] == ["chill"]
    assert profile["favorited_event_ids"] == ["fav-1", "fav-2"]


def test_build_profile_parses_price_range_into_numeric_max():
    user = _mock_user(price_range="$0-$30")
    profile = _build_profile(user, [])
    assert profile["price_max"] == 30.0


def test_build_profile_price_max_none_for_unparsable_price():
    user = _mock_user(price_range="$$$")
    profile = _build_profile(user, [])
    assert profile["price_max"] is None


def test_build_profile_carries_neighborhood():
    user = _mock_user(neighborhood="Echo Park")
    profile = _build_profile(user, [])
    assert profile["neighborhood"] == "Echo Park"


def test_build_profile_neighborhood_none_when_unset():
    user = _mock_user(neighborhood=None)
    profile = _build_profile(user, [])
    assert profile["neighborhood"] is None
