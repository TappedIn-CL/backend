# AI Task Doc

## Preliminary Tasks (Easy)

- Implement `chip_mapping.py` shared between frontend and backend to have source of truth.
- `taxonomy.py` is not connected to `agent/nodes.py` — all event metadata is inlined instead of imported (Charlton).

---

## Tasks

| # | Task | Owner | Status |
|---|---|---|---|
| 1 | `GET /events/by-ids` endpoint | Rohan | In progress |
| 2 | `hydrate_events` node + graph wiring | Allen + Rohan | In progress |
| 3 | Re-wire `retrieve_events` to real Pinecone | Charlton or Rohan | Not started — was reverted |
| 4 | Stage scraper → enrichment → Pinecone in cron | Charlton | Not started |
| 5 | One-time backfill to populate Pinecone now | Whoever owns #4 | Not started |

---

## Current Agent Logic Chain

```
1. Scraper runs       → writes raw events to Supabase
                          ↓ (UUIDs assigned and stable per source+source_id)
2. Enrichment runs    → adds canonical category/tags/vibe_tags to those Supabase rows
                          ↓ (still in Supabase)
3. Embed + upsert     → reads Supabase rows, generates 1536-dim vectors,
                         upserts (uuid, vector, sparse metadata) into Pinecone
                          ↓
4. Pinecone now has   → vectors + filterable metadata indexed by UUID
                          ↓
5. User query fires   → retrieve_events embeds the query, searches Pinecone
                          ↓
6. Pinecone returns   → list of matched UUIDs + sparse metadata
                          ↓
7. hydrate_events     → calls GET /events/by-ids?ids=<those UUIDs>
                          ↓
8. Endpoint returns   → full Supabase rows (description, vibe_tags, etc.)
                          ↓
9. score_and_rank     → cosine-blends and sorts
                          ↓
10. SSE response      → frontend renders rich event cards
```

---

## Schema Mismatch: EventSchema vs Event Model

| EventSchema (Allen expects) | Event model (Raphael has) | Action |
|---|---|---|
| `id: str` | `id: UUID` | str-cast on serialization |
| `title: str` | `title: String` | passthrough |
| `description: str` | `description: String (nullable)` | passthrough, default "" |
| `category: str` | `category: String (nullable)` | passthrough, default "" |
| `tags: list[str]` | `special_tags: String (CSV)` | split on `,` |
| `vibe_tags: list[str]` | `vibe_tags: String (CSV)` | split on `,` |
| `venue_name: str` | (missing) | derive from `location` or placeholder |
| `address: str` | `location: String (nullable)` | rename location → address |
| `city: str` | (missing) | hardcode "Los Angeles" for demo |
| `latitude: float` | (missing) | 0.0 placeholder |
| `longitude: float` | (missing) | 0.0 placeholder |
| `price_min: float` | `cost: Float` | duplicate cost into both |
| `price_max: float` | `cost: Float` | duplicate cost into both |
| `start_time: str (ISO)` | `date: DateTime` | `.isoformat()` |
| `end_time: Optional[str]` | (missing) | None for demo |
| `image_url: Optional[str]` | (missing) | None for demo |
| `source_url: str` | (missing) | None for demo |

---

## Rohan's Steps 1–4

1. Add hydrated response schema in `schemas/event.py`. **Don't tighten** category/tags to existing Literal types yet — Raphael's `EventCategory` has "Arts", "Family", "Fashion" which aren't in `agent/taxonomy.py`. Vocabulary-drift cleanup is a separate task.
2. Add translator to `app/utils/event_utils.py`.
3. Add batch endpoint to `app/routers/event.py`. Imports add `event_to_hydrated` and `HydratedEventResponse`. Insert new route between `list_events` and `get_event`.
4. Smoke test and commit.

`GET /events/by-ids?ids=uuid1,uuid2,...` ships on `rohan/events-by-ids` (PRing into `soft-delete-events`). Response shape matches `agent/state.py::EventSchema` exactly. Order preserved per request. Up to 100 IDs per call.

Once PR merges, point `BACKEND_URL=http://localhost:8000` in the agent — hydrate node will work.

---

## Allen's Hydrate Step

```bash
git checkout charlton/recommendation-scorer
git pull
git checkout -b allen/hydrate-events
```

Branching off Charlton's branch (not AI-dev) because that's where scoring + `compute_taste` live.

### Reference Implementation

```python
import httpx

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
HYDRATION_TIMEOUT_SECONDS = 5.0
MAX_HYDRATION_BATCH = 100

def hydrate_events(state: AgentState) -> AgentState:
    candidates = state.get("candidate_events") or []
    if not candidates:
        return {**state, "hydrated_events": []}

    ids = [e["id"] for e in candidates][:MAX_HYDRATION_BATCH]

    try:
        response = httpx.get(
            f"{BACKEND_URL}/events/by-ids",
            params={"ids": ",".join(ids)},
            timeout=HYDRATION_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        full_rows = response.json()

        rows_by_id = {row["id"]: row for row in full_rows}
        hydrated: list[EventSchema] = []
        for candidate in candidates:
            full = rows_by_id.get(candidate["id"])
            if full is None:
                logger.warning(
                    "Event %s in Pinecone but missing from Supabase — falling back to sparse data",
                    candidate["id"],
                )
                hydrated.append(candidate)
            else:
                hydrated.append({**candidate, **full})

    except Exception as e:
        logger.error("Hydration failed, returning sparse candidates: %s", e)
        hydrated = list(candidates)

    return {**state, "hydrated_events": hydrated}
```

### Allen's Test

```bash
python -c "
import os
os.environ['BACKEND_URL'] = 'http://localhost:8000'
from agent.nodes import hydrate_events

state = {
    'candidate_events': [
        {'id': '<uuid1>'},
        {'id': '<uuid2>'},
    ],
}
result = hydrate_events(state)
print('Hydrated count:', len(result['hydrated_events']))
for e in result['hydrated_events']:
    print(f\"  - {e.get('title')}: desc={bool(e.get('description'))}, vibes={e.get('vibe_tags')}\")
"
```

If `desc=True` and `vibes` is non-empty, hydration works.

---

## Missing: Pinecone has no real events (Charlton + Rohan)

```
GitHub Actions cron (every 3 hours)
  ├─ Stage 1: SCRAPE
  │   └─ scrapers/uncoverla.py → upsert Supabase
  │
  ├─ Stage 2: ENRICH        ← MISSING
  │   └─ ingestion/enrichment.py → enrich each Supabase event
  │
  └─ Stage 3: EMBED + UPSERT TO PINECONE   ← MISSING
       └─ ingestion/embed.py → vectorize + upsert
```

### Steps

1. Build/extend `run_pipeline.py` (Charlton's enrichment-backfill task expanded to also cover embed+upsert).
2. Run it once locally to populate Pinecone.
3. Re-wire `retrieve_events` to actually search Pinecone (re-apply Charlton's reverted commit `1fe68c2`).
4. Update cron to call `run_pipeline.py`.

```bash
# Step 1: confirm Supabase has data
psql $DATABASE_URL -c "SELECT count(*), source FROM events GROUP BY source;"

# Step 2: confirm Pinecone is empty
python -c "from agent.pinecone_client import _get_index; print(_get_index().describe_index_stats())"

# Step 4: run backfill once
python -m scrapers.run_pipeline

# Step 5: verify Pinecone now has vectors
python -c "from agent.pinecone_client import _get_index; print(_get_index().describe_index_stats())"
```

---

## SSE Logic (after the above)

SSE needs `POST /agent/query` to exist as a FastAPI route — **Shaun's task** in Week 4 backend plan, not Charlton's or Rohan's.

- **Backend (Shaun)**: builds `POST /agent/query` route, wraps in `StreamingResponse(media_type="text/event-stream")`, calls `graph.astream(...)`, formats each yielded chunk as SSE.
- **AI (Charlton/Rohan)**: ensures graph supports `astream()`. LangGraph supports natively, mostly verifying nodes are async-compatible.

**Hard dependency on Shaun.** If `POST /agent/query` isn't shipped, SSE is impossible regardless of AI work.

Frontend SSE consumption is **Jason's** task.

---

## Also

- Implement `chip_mapping.py` (shared frontend/backend source of truth).
- Logging + Analytics (Charlton): every query run writes a row to `query_logs` (raw query, parsed filters, top result ID, user ID, latency).
