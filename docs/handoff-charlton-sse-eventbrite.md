# Handoff for Charlton — SSE Async + Eventbrite Pipeline Integration

**Author:** Rohan
**Branch you'll work on:** `rohan-dev` (or fork off it)
**Estimated effort:** 3–5 hours total (2h Task A + 2–3h Task B)

---

## Context (what's already done)

The agent pipeline now works end-to-end. You can verify by running [test_hydration_e2e.py](../test_hydration_e2e.py):

```
parse_intent → retrieve_events (Pinecone + dedup) → hydrate_events (HTTP → /events/by-ids → Supabase) → compute_taste → score_and_rank (cosine blend)
```

Recent verified additions:
- [agent/nodes.py:122](../agent/nodes.py#L122) — `_to_pinecone_filter` translates `categories`/`tags` to Pinecone `$in` syntax
- [agent/nodes.py:155](../agent/nodes.py#L155) — title-based dedup in `retrieve_events` (Pinecone has duplicate vectors from re-scrapes; dedup picks the highest-similarity match)
- [agent/nodes.py:200](../agent/nodes.py#L200) — Allen's `hydrate_events` node calls `GET /events/by-ids` and merges full Supabase rows
- [agent/nodes.py:288](../agent/nodes.py#L288) — `score_and_rank` uses real cosine blend (`0.7 * cos(query) + 0.3 * cos(taste)`) via `fetch_vectors` + `score_events`
- [agent/scoring.py:55](../agent/scoring.py#L55) — `score_events` now attaches `score` field to each returned event
- Pinecone was cleaned of 67 orphan vectors (UUIDs not in Supabase). Index now has 77 valid vectors all matching enriched Supabase rows.

Pipeline is verified working with both cold-start (no taste) and a user_profile (taste blend influences ranking). See test output in `test_hydration_e2e.py`.

**What's NOT yet shipped:** SSE streaming endpoint, Eventbrite integration into cron.

---

## Task A — Make `hydrate_events` async (for SSE)

### Why
Shaun is building `POST /agent/query` with `StreamingResponse(media_type="text/event-stream")`. The route will use `graph.astream()` to yield per-phase chunks so the frontend can show progress (Parsing → Retrieving → Hydrating → Scoring → Results).

LangGraph's `astream()` does work with sync nodes, but `hydrate_events` makes a **blocking** `httpx.get()` call that can take up to 5 seconds. During that window the entire event loop is blocked — no other node yields, the SSE connection stalls, and the frontend's loading indicator freezes. Converting to `httpx.AsyncClient` unblocks the loop and lets `compute_taste` (which is CPU-only, fast) run concurrently if topology allows.

### Files
- [agent/nodes.py](../agent/nodes.py) — convert `hydrate_events` to `async def`

### Implementation

```python
# agent/nodes.py — replace the existing httpx.get block

async def hydrate_events(state: AgentState) -> AgentState:
    candidates = state.get("candidate_events") or []
    if not candidates:
        return {**state, "hydrated_events": []}

    if len(candidates) > MAX_HYDRATION_BATCH:
        logger.warning(
            "hydrate_events: %d candidates exceed batch cap %d; truncating",
            len(candidates), MAX_HYDRATION_BATCH,
        )
    ids = [e["id"] for e in candidates][:MAX_HYDRATION_BATCH]

    try:
        async with httpx.AsyncClient(timeout=HYDRATION_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{BACKEND_URL}/events/by-ids",
                params={"ids": ",".join(ids)},
            )
        resp.raise_for_status()
        full_rows = resp.json()
        # ... rest stays identical (merge loop)
    except Exception as e:
        logger.error("Hydration failed, returning sparse candidates: %s", e)
        hydrated = list(candidates)

    return {**state, "hydrated_events": hydrated}
```

### Verify graph.astream() yields per-node chunks

LangGraph compiles async + sync nodes into the same graph. Add this quick script:

```python
# scripts/test_astream.py
import asyncio
from dotenv import load_dotenv; load_dotenv()
from agent.graph import agent

async def main():
    initial = {"query": "fun food event in LA", "chips": [], "user_profile": None}
    async for chunk in agent.astream(initial):
        node_name = next(iter(chunk.keys()))
        print(f"[{node_name}] yielded")

asyncio.run(main())
```

Expected output:
```
[parse_intent] yielded
[retrieve_events] yielded
[hydrate_events] yielded
[compute_taste] yielded
[score_and_rank] yielded
```

### Acceptance criteria — Task A
- [ ] `hydrate_events` is `async def`, uses `httpx.AsyncClient`
- [ ] `agent.invoke(initial)` still works (sync caller path — `test_hydration_e2e.py` must still pass)
- [ ] `agent.astream(initial)` yields 5 chunks in order
- [ ] No `RuntimeError: asyncio.run() cannot be called from a running event loop` warnings

---

## Task B — Pull main + integrate Eventbrite scraper into cron

### Why
The cron job currently only scrapes UncoverLA. Melinda merged the Eventbrite scraper into `main` last week — it's not on `rohan-dev` yet. We need Eventbrite events flowing through the same `scrape → enrich → embed → upsert` pipeline so the cron job hits both sources every 3 hours.

### Files involved

**On main (need to be pulled in):**
- `scrapers/eventbrite.py` — Melinda's Eventbrite scraper
- `scrapers/date_utils.py` — date parsing helpers used by Eventbrite

**On rohan-dev (need to be updated):**
- `scrapers/run_pipeline.py` — currently only calls `from scrapers.uncoverla import run_scrape`. Must call both UncoverLA and Eventbrite.

### Steps

#### 1. Pull main into rohan-dev
```bash
git checkout rohan-dev
git pull origin main
# Expect conflicts in:
#   .github/workflows/ingest.yml  → KEEP rohan-dev (uses run_pipeline.py)
#   app/main.py                   → TAKE main (adds Shaun's agent router)
#   app/models/event.py           → MERGE (main may have is_active column)
#   app/routers/event.py          → KEEP rohan-dev (has /by-ids route)
#   app/utils/event_utils.py      → KEEP rohan-dev
#   schemas/event.py              → KEEP rohan-dev (has HydratedEventResponse)
#   scrapers/uncoverla.py         → KEEP rohan-dev (has run_scrape() refactor)
#   requirements.txt              → UNION both
```

Reference: I started this merge earlier and aborted. The full conflict list and resolutions are in [scrapers/run_pipeline.py](../scrapers/run_pipeline.py) (kept) and [agent/](../agent/) (entirely kept from rohan-dev).

#### 2. Refactor `scrapers/eventbrite.py` to expose `run_scrape()`

Currently its scraping logic lives inside `if __name__ == "__main__":` — extract it like `scrapers/uncoverla.py` already does. Pattern:

```python
# scrapers/eventbrite.py

def run_scrape() -> int:
    """Scrape Eventbrite, classify with OpenAI, upsert to Supabase. Returns count."""
    total = 0
    for page in range(1, 4):
        try:
            events = get_events_from_page(page=page)
            if not events:
                break
            categories = classify_categories_with_openai(events)
            for i, e in enumerate(events):
                e["category"] = categories.get(i, "Other")
            added = save_events_to_db(events)
            total += added
        except Exception as e:
            print(f"  → Error on page {page}: {e}")
    print(f"\nDone. Total Eventbrite events saved: {total}")
    return total


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "../.env"))
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    run_scrape()
```

#### 3. Set `source = "eventbrite"` in `save_events_to_db()`

UncoverLA already does this in [scrapers/uncoverla.py:159](../scrapers/uncoverla.py#L159):
```python
"source": "uncoverla",
"source_id": source_id,   # stable hash of article URL + title + date
```

Eventbrite's `save_events_to_db()` must do the same with `source = "eventbrite"` and `source_id = hashlib.md5(<event_url> or <title+date>).hexdigest()`. This makes the upsert idempotent — re-scraping the same Eventbrite listing UPDATEs the existing row instead of creating duplicates.

#### 4. Update `scrapers/run_pipeline.py` to call both scrapers

```python
# scrapers/run_pipeline.py — replace stage_scrape

from scrapers.uncoverla import run_scrape as run_uncoverla
from scrapers.eventbrite import run_scrape as run_eventbrite

def stage_scrape() -> int:
    logger.info("=== Stage 1: SCRAPE ===")
    total = 0
    try:
        logger.info("--- UncoverLA ---")
        total += run_uncoverla()
    except Exception as e:
        logger.error("UncoverLA scrape failed: %s", e)
    try:
        logger.info("--- Eventbrite ---")
        total += run_eventbrite()
    except Exception as e:
        logger.error("Eventbrite scrape failed: %s", e)
    return total
```

**Important:** wrap each scraper in its own try/except so an Eventbrite outage doesn't kill the UncoverLA run (and vice versa). The enrich + embed stages will pick up whatever made it into Supabase.

#### 5. Verify the Supabase row shape is the same for both

Both scrapers must populate the same `events` table columns so `stage_enrich` and `stage_embed` work uniformly:

| Column | UncoverLA | Eventbrite | Required for enrich? |
|---|---|---|---|
| `id` | UUID4 | UUID4 | yes |
| `title` | yes | yes | yes (used in LLM prompt) |
| `description` | from article | from Eventbrite listing | yes (used in LLM prompt) |
| `date` | parsed ISO | parsed ISO | yes (filter on future events) |
| `location` | venue + address | venue + address | yes (used in LLM prompt) |
| `category` | LLM-extracted | LLM-extracted | populated by stage_enrich |
| `special_tags` | null until enrich | null until enrich | populated by stage_enrich |
| `vibe_tags` | null until enrich | null until enrich | populated by stage_enrich |
| `source` | `"uncoverla"` | `"eventbrite"` | yes (for dedup + debugging) |
| `source_id` | md5 hash | md5 hash | yes (ON CONFLICT key) |

`stage_enrich` queries `WHERE vibe_tags IS NULL` — it doesn't care about source. So Eventbrite events flow through the same enrichment + embedding logic with zero changes once they land in Supabase with the right shape.

#### 6. Run the pipeline locally to verify

```bash
cd backend
PYTHONIOENCODING=utf-8 python scrapers/run_pipeline.py
```

Expected stages:
```
=== Stage 1: SCRAPE ===
--- UncoverLA ---
Fetching article links...
... saved N events
--- Eventbrite ---
Fetching page 1...
... saved M events
=== Stage 2: ENRICH ===
Found (N+M) events lacking vibe_tags
✓ ... → category=... tags=... vibes=...
=== Stage 3: EMBED + UPSERT ===
Enriched=X, already in Pinecone=Y, to index=Z
Upserted Z events to Pinecone
Pipeline complete
```

Then run the smoke test to confirm both sources appear in agent results:

```bash
PYTHONIOENCODING=utf-8 python test_hydration_e2e.py
```

You should see events from both sources in the ranked output. Quick sanity check in psql or Supabase Studio:

```sql
SELECT source, COUNT(*) FROM events WHERE vibe_tags IS NOT NULL GROUP BY source;
-- expect both 'uncoverla' and 'eventbrite' rows
```

### Acceptance criteria — Task B
- [ ] `rohan-dev` merged with `main`, all conflicts resolved
- [ ] `scrapers/eventbrite.py` exposes `run_scrape()` callable
- [ ] `save_events_to_db()` in eventbrite.py sets `source="eventbrite"` and a stable `source_id`
- [ ] `scrapers/run_pipeline.py` calls both scrapers in `stage_scrape`, each in its own try/except
- [ ] Local pipeline run completes all 3 stages without error
- [ ] Supabase has events with `source IN ('uncoverla', 'eventbrite')`
- [ ] Pinecone vector count goes up (re-run pipeline, then check `idx.describe_index_stats()`)
- [ ] `test_hydration_e2e.py` still passes (i.e. nothing broke downstream)
- [ ] `.github/workflows/ingest.yml` still runs `python scrapers/run_pipeline.py` (no change needed there, just verify)

---

## Sequence

Do **Task B first** — it's the higher-priority piece since it affects what events users see. Async hydration (Task A) is a polish for when Shaun ships SSE; the pipeline runs fine without it.

```
Day 1:  Task B (merge + Eventbrite integration)         → ~3 hours
Day 2:  Task A (async hydrate_events + astream verify)  → ~2 hours
        → ping Shaun that hydrate_events is async-ready
```

---

## Open questions / edge cases

1. **Eventbrite rate limits.** Pages 1–3 hit the public listing page; no auth. If they 429 us, swap to their official API (requires registering an app). Defer until we actually see 429s.
2. **Duplicate events across sources.** UncoverLA and Eventbrite may list the same event. The runtime dedup in `retrieve_events` ([agent/nodes.py:155](../agent/nodes.py#L155)) keys on title-only — should catch most cross-source dupes. Title drift between sources may still let some through. Acceptable for demo.
3. **Date filter.** `scrapers/date_utils.py` from main has `is_current_or_future_event()` — Eventbrite uses this to skip past events. UncoverLA does NOT have this filter yet — could add it for consistency, but not blocking.
4. **`Other` category in Eventbrite.** Eventbrite's LLM classifier may emit `"Other"` for events that don't fit the 8 main categories. That's compatible with our taxonomy (`agent/taxonomy.py` includes `"Other"`).

---

## Who to ping if blocked

- **Pipeline / scoring / agent logic** → Rohan
- **SSE route, FastAPI integration, agent/query schema** → Shaun
- **Eventbrite scraper specifics, original Eventbrite PR** → Melinda
- **Frontend SSE consumption** → frontend lead (whoever owns Landing.tsx)
