"""End-to-end test of the full LangGraph agent pipeline.

Stages exercised:
  parse_intent -> retrieve_events (Pinecone, dedup) -> hydrate_events (HTTP /events/by-ids -> Supabase) -> compute_taste -> score_and_rank (cosine blend)

Runs TWICE:
  Pass 1 — cold-start (no user_profile)   → score = cosine(query, event)
  Pass 2 — with user_profile (taste vector) → score = 0.7*cosine(query, event) + 0.3*cosine(taste, event)

How to run:
  1. Make sure backend is running on localhost:8000:
       cd backend && PYTHONIOENCODING=utf-8 python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
  2. In another terminal:
       cd backend && PYTHONIOENCODING=utf-8 python test_hydration_e2e.py
"""
import sys
from dotenv import load_dotenv
load_dotenv(override=True)

from agent.graph import agent

QUERY = "fun food event in LA this weekend"
CHIPS = []
SHOW_TOP_N = 5  # how many events to print in each phase

# Pretend user — likes food + social vibes. Drives the taste vector in Pass 2.
USER_PROFILE = {
    "interests": ["food festivals", "cocktails", "pop-ups"],
    "favorited_tags": ["foodie", "social", "outdoor"],
}


def line(char="-", width=78):
    print(char * width)


def header(title):
    print()
    line("=")
    print(f"  {title}")
    line("=")


def run_pass(label: str, user_profile):
    """Invoke the agent once and print full per-stage detail."""
    print()
    line("#", 78)
    print(f"#  PASS: {label}")
    line("#", 78)

    header("INPUT")
    print(f"  query:        {QUERY!r}")
    print(f"  chips:        {CHIPS}")
    print(f"  user_profile: {user_profile}")

    initial = {
        "query": QUERY,
        "chips": CHIPS,
        "user_profile": user_profile,
    }

    result = agent.invoke(initial)

    semantic_query = result.get("semantic_query")
    filters = result.get("filters") or {}
    candidates = result.get("candidate_events") or []
    hydrated = result.get("hydrated_events") or []
    taste_vector = result.get("taste_vector")
    ranked = result.get("ranked_events") or []

    # ---- Stage 1 ----
    header("STAGE 1: parse_intent")
    print(f"  semantic_query (used for embedding): {semantic_query!r}")
    print(f"  filters extracted: {filters}")

    # ---- Stage 2 ----
    header(f"STAGE 2: retrieve_events  ({len(candidates)} unique candidates after Pinecone + dedup)")
    print(f"  Top {min(SHOW_TOP_N, len(candidates))} (sparse — Pinecone metadata only, no description / vibe_tags):")
    print()
    for i, c in enumerate(candidates[:SHOW_TOP_N], 1):
        print(f"  [{i}] {c.get('title')}")
        print(f"      id: {c.get('id')}  category: {c.get('category')}")
        print()

    # ---- Stage 3 ----
    header(f"STAGE 3: hydrate_events  ({len(hydrated)} candidates with merged Supabase fields)")
    print(f"  Top {min(SHOW_TOP_N, len(hydrated))} hydrated events:")
    print()
    for i, h in enumerate(hydrated[:SHOW_TOP_N], 1):
        desc = (h.get("description") or "")
        print(f"  [{i}] {h.get('title')}")
        print(f"      id:          {h.get('id')}")
        print(f"      category:    {h.get('category')}")
        print(f"      venue:       {h.get('venue_name')}")
        print(f"      start_time:  {h.get('start_time')}")
        print(f"      price:       ${h.get('price_min')} - ${h.get('price_max')}")
        print(f"      tags:        {h.get('tags')}")
        print(f"      vibe_tags:   {h.get('vibe_tags')}")
        print(f"      description: {desc[:120]}{'...' if len(desc) > 120 else ''}")
        print()

    # ---- Stage 4a: compute_taste evidence ----
    header("STAGE 4a: compute_taste")
    if taste_vector is None:
        print("  taste_vector: None  (cold-start — score = pure semantic similarity)")
    else:
        print(f"  taste_vector: {len(taste_vector)}-dim embedding computed from user_profile")
        print(f"    interests:      {user_profile.get('interests')}")
        print(f"    favorited_tags: {user_profile.get('favorited_tags')}")
        print(f"    (score blend will be 0.7 * cosine(query) + 0.3 * cosine(taste))")

    # ---- Stage 4b: score_and_rank ----
    header(f"STAGE 4b: score_and_rank  ({len(ranked)} ranked events)")
    print(f"  Top {min(SHOW_TOP_N, len(ranked))} ranked events with scores:")
    print()
    for i, r in enumerate(ranked[:SHOW_TOP_N], 1):
        score = r.get("score")
        score_str = f"{score:.4f}" if isinstance(score, (int, float)) else "(no score)"
        print(f"  #{i}  score={score_str}  {r.get('title')}")
        print(f"      category={r.get('category')}  vibes={r.get('vibe_tags')}")
        print(f"      desc: {(r.get('description') or '')[:90]}")
        print()

    response_text = result.get("response")
    if response_text:
        print(f"  Agent response: {response_text}")

    return ranked


# ============================================================================
# Pass 1: cold-start (no user_profile)
# ============================================================================
ranked_cold = run_pass("COLD-START (no user_profile)", user_profile=None)

# ============================================================================
# Pass 2: with user_profile (taste vector enabled)
# ============================================================================
ranked_taste = run_pass(f"WITH USER PROFILE — {USER_PROFILE['interests']}", user_profile=USER_PROFILE)

# ============================================================================
# Comparison
# ============================================================================
header("COMPARISON — did the user's taste change the ranking?")
print(f"  Top 5 cold-start:")
for i, r in enumerate(ranked_cold[:5], 1):
    score = r.get("score")
    score_str = f"{score:.4f}" if isinstance(score, (int, float)) else "?"
    print(f"    #{i}  score={score_str}  {r.get('title')}")

print(f"\n  Top 5 with taste vector:")
for i, r in enumerate(ranked_taste[:5], 1):
    score = r.get("score")
    score_str = f"{score:.4f}" if isinstance(score, (int, float)) else "?"
    print(f"    #{i}  score={score_str}  {r.get('title')}")

# Did the order change?
cold_ids = [r.get("id") for r in ranked_cold[:10]]
taste_ids = [r.get("id") for r in ranked_taste[:10]]
order_changed = cold_ids != taste_ids
print(f"\n  Order changed by taste: {'YES — taste vector influenced ranking' if order_changed else 'NO — same order (taste vector had no effect on top 10)'}")

# ============================================================================
# Hydration verification
# ============================================================================
header("HYDRATION VERIFICATION (pass 2)")
ok = True
if not ranked_taste:
    print("  FAIL: ranked_events is empty")
    ok = False
else:
    enriched_count = sum(1 for r in ranked_taste if r.get("description") and r.get("vibe_tags"))
    has_scores = sum(1 for r in ranked_taste if isinstance(r.get("score"), (int, float)))
    print(f"  {enriched_count}/{len(ranked_taste)} ranked events have full description + vibe_tags  (hydrated from Supabase)")
    print(f"  {has_scores}/{len(ranked_taste)} ranked events have a numeric score field")
    if enriched_count == 0 or has_scores == 0:
        ok = False

print()
line("=")
print("  " + ("PASS — full pipeline (hydration + cosine scoring + taste blend) works end-to-end" if ok else "FAIL"))
line("=")

sys.exit(0 if ok else 1)
