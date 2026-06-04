"""Tests for the AgentState seed contract and the request coordinate fields.

The contract-invariant test guards against the seed dict silently drifting out
of sync with AgentState when fields are added in future.
"""

from agent.state import AgentState, initial_state
from schemas.agent import AgentQueryRequest


def test_initial_state_keys_match_agentstate_contract():
    state = initial_state(query="q", chips=[], user_profile=None, user_lat=None, user_lng=None)
    assert set(state.keys()) == set(AgentState.__annotations__.keys())


def test_initial_state_defaults_new_fields():
    state = initial_state(
        query="q", chips=["Chill"], user_profile=None, user_lat=1.0, user_lng=2.0
    )
    assert state["query"] == "q"
    assert state["chips"] == ["Chill"]
    assert state["user_lat"] == 1.0
    assert state["user_lng"] == 2.0
    assert state["time_intent"] is None
    assert state["happening_now"] is False
    assert state["confidence"] is None
    assert state["enriched_events"] == []


def test_initial_state_passes_through_user_profile():
    profile = {"interests": ["jazz"]}
    state = initial_state(query="q", chips=[], user_profile=profile, user_lat=None, user_lng=None)
    assert state["user_profile"] == profile


def test_agent_query_request_accepts_coords():
    req = AgentQueryRequest(query="q", chips=[], user_lat=34.0, user_lng=-118.0)
    assert req.user_lat == 34.0
    assert req.user_lng == -118.0


def test_agent_query_request_coords_default_none():
    req = AgentQueryRequest(query="q")
    assert req.user_lat is None
    assert req.user_lng is None
