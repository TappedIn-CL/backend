# Week 2 Plan — Apr 21 → Apr 28

**Theme:** Close out Week 1 leftovers + ship Week 4 data ingestion pipeline early.

**Week 2 goal:** By next Tuesday, a user should be able to (1) sign up with email or Google via Supabase Auth, (2) land on a profile-loaded landing page, (3) type a query into the search bar, and (4) see real LA events returned from Supabase that were scraped and ingested on a schedule.

---

## 1. Process Changes

These apply to everyone starting now:

- **All branches must go through PRs into `main`.** No more direct pushes to main.
- **Commit messages must be descriptive.** No more "landing page" or "login and sign up." Use the format `<area>: <what changed>` (e.g., `frontend: wire AuthModal to supabaseClient`, `backend: add Event SQLAlchemy model`).
- **PR descriptions must include what, why, and how to test.** Template: Summary / Changes / Test plan.
- **Every subteam creates one PR per deliverable**, not per day.

---

## 2. Leftover Week 1 Tasks (finish by Thursday)

### Frontend
- **Aadarsh:** Wire `AuthModal` on `main` to Shaun's Supabase client (port `supabaseClient.ts`, `AuthContext.tsx`, `features/auth/*` from the `auth` branch). Replace `alert()` placeholders with real `signIn`/`signUp`/`signInWithGoogle` calls.
- **Kyle:** Align landing page with the design lofis (currently doesn't match). Joint meeting with design needed ASAP.
- **Melinda/Jason:** Wire search bar on landing page to hit backend `GET /events` (currently filters a local array only). Use mock events from backend once Raphael's endpoints land.

### Backend
- **Joyce:** Open PR for user model branch. Include demographic fields + `GET /users/me` that returns full profile (not just JWT payload).
- **Raphael:** Open PR for event model + `GET /events`, `POST /events`, `GET /events/{id}` endpoints. Schema must match [event-schema.md](event-schema.md).
- **Shaun:** Review Joyce's user model PR. Verify `/users/me` returns profile data on authenticated requests.
- **Rohan:** Review Raphael's event model PR against the canonical schema.

### AI
- **Rohan/Allen:** Swap `MOCK_EVENTS` in `agent/nodes.py` for real Supabase reads once Raphael's endpoints are live. Wire `retrieve_events` to hit Pinecone instead of returning hardcoded data.
- **Charlton:** Verify end-to-end agent flow with real Supabase + Pinecone data.

### Design
- **Taey:** Finalize event card component — reference apps: Eventbrite, Luma, Partiful, Airbnb listings.
- **Nancy/Patrick:** Deliver lofis for event feed page (search bar + results grid + filter chips). Prep event page lofis for next week.

---

## 3. Week 2 New Goal: Data Ingestion Pipeline

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                   Scheduler (GitHub Actions cron)                │
│                   Runs every 3 hours                             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                  backend/ingestion/run.py                        │
│                                                                  │
│   ┌─────────────────┐   ┌─────────────────┐   ┌─────────────┐  │
│   │ Eventbrite API  │   │ BeautifulSoup   │   │ Apify /     │  │
│   │ client          │   │ scrapers        │   │ Instaloader │  │
│   │ (structured)    │   │ (UncoverLA,     │   │ (IG popups) │  │
│   │                 │   │  PopUpLA, DoLA) │   │             │  │
│   └────────┬────────┘   └────────┬────────┘   └──────┬──────┘  │
│            │                     │                    │         │
│            └─────────────────────┼────────────────────┘         │
│                                  ▼                               │
│                        Raw event dicts                           │
│                                  │                               │
│                                  ▼                               │
│              ┌────────────────────────────────┐                 │
│              │ LLM enrichment (GPT-4o-mini)   │                 │
│              │ → category, tags, vibe_tags    │                 │
│              └────────────────────────────────┘                 │
│                                  │                               │
│                                  ▼                               │
│              ┌────────────────────────────────┐                 │
│              │ Deduplicate by source_id/url    │                 │
│              │ Upsert into Supabase events    │                 │
│              └────────────────────────────────┘                 │
│                                  │                               │
│                                  ▼                               │
│              ┌────────────────────────────────┐                 │
│              │ Embed new events via OpenAI    │                 │
│              │ Upsert vectors into Pinecone   │                 │
│              └────────────────────────────────┘                 │
└─────────────────────────────────────────────────────────────────┘
```

### Scope cuts for Week 2 MVP

- **Eventbrite API first.** It's structured, free, and reliable. Prove the full pipeline end-to-end with Eventbrite before touching scrapers.
- **BeautifulSoup for 1 site, not 3.** Pick UncoverLA. Add the others in Week 3.
- **Instagram is a stretch goal.** If Apify/instaloader doesn't pan out by Friday, push to Week 3. Don't block the pipeline on it.
- **No ElasticSearch.** Postgres + Pinecone are sufficient for Week 2.
- **No PostGIS yet.** Use naive lat/lng distance math until we need more.

---

## 4. Subteam Task Breakdown

### Backend (Raphael, Joyce, Shaun)

| Priority | Task | Owner |
|---|---|---|
| P0 | Merge Event model PR | Raphael |
| P0 | Merge User model PR with demographic fields | Joyce |
| P0 | `GET /users/me` returns full profile from DB (not just JWT payload) | Joyce |
| P0 | `GET /events`, `POST /events`, `GET /events/{id}` | Raphael |
| P1 | Create `backend/ingestion/` folder with scaffolding (`run.py`, `sources/`, `enrichment.py`) | Shaun |
| P1 | Eventbrite API client — pull events for LA with `venue.location.city=Los Angeles` | Raphael |
| P1 | BeautifulSoup scraper for UncoverLA events page | Joyce |
| P2 | Deduplication logic — upsert by `(source, source_id)` unique constraint | Raphael |
| P2 | GitHub Actions workflow `.github/workflows/ingest.yml` running every 3 hours | Shaun |

### AI (Rohan, Charlton, Allen)

| Priority | Task | Owner |
|---|---|---|
| P0 | Wire `retrieve_events` node to real Pinecone (stop using MOCK_EVENTS) | Rohan |
| P0 | LLM enrichment function — input: raw scraped dict, output: normalized `{category, tags, vibe_tags}` from canonical enums | Charlton |
| P0 | `ingestion/embed.py` — embed events via `build_embedding_text`, upsert to Pinecone with metadata | Rohan |
| P1 | `parse_intent` node — real LLM call that extracts `{price_max, date_range, tags_required, distance}` from NL query | Charlton |
| P1 | Hydration step — after Pinecone query returns IDs, fetch full event rows from Supabase | Allen |
| P2 | Apify or instaloader integration for Instagram popup accounts (5-10 curated accounts to start) | Allen |

### Frontend (Kyle, Melinda, Aadarsh, Jason)

| Priority | Task | Owner |
|---|---|---|
| P0 | Wire `AuthModal` to real Supabase client (port from `auth` branch) | Aadarsh |
| P0 | `useAuth` hook calls `GET /users/me` after login, stores profile in context | Aadarsh |
| P0 | Landing page matches design lofis | Kyle + Melinda |
| P0 | Search bar hits real `GET /events?q=...` (or agent endpoint once ready) | Melinda |
| P1 | Event feed page — grid of event cards using Taey's component spec | Jason |
| P1 | Event card component — default/hover/loading states per design | Jason |
| P1 | `/profile` page showing user's email + demographic data from `/users/me` | Kyle |
| P2 | Filter chips UI on feed page (category, price, date chips) | Melinda |

### Design (Taey, Nancy, Patrick)

| Priority | Task | Owner |
|---|---|---|
| P0 | Event card final spec — default, hover, saved, skeleton | Taey |
| P0 | Event feed page lofis — search + grid + filter chips | Nancy |
| P1 | Joint session with Kyle/Melinda to align landing page with lofis | Taey + Kyle |
| P1 | Agent query flow lofis — search bar, streaming response UI, results view | Patrick |
| P2 | Event detail page lofis (click into a card) | Nancy |

---

## 5. Critical Path / Dependency Chain

```
Raphael Event model PR ──┐
                         ├──→ AI ingestion ──→ Frontend real event feed
Joyce User model PR ─────┤
                         └──→ Aadarsh profile load ──→ Landing page E2E flow
Design event card spec ──┘
```

**If Raphael's PR slips past Thursday, everything downstream slips.** This should be the single highest-priority item in the backend team's queue.

---

## 6. Proposed Ingestion Pipeline Design

### File structure
```
backend/ingestion/
├── __init__.py
├── run.py               # main entry point, orchestrates the full job
├── sources/
│   ├── __init__.py
│   ├── eventbrite.py    # Eventbrite API client
│   ├── uncoverla.py     # BeautifulSoup scraper
│   └── instagram.py     # Apify/instaloader (optional)
├── enrichment.py        # LLM call to extract category/tags/vibes
├── dedupe.py           # upsert logic via (source, source_id)
└── embed.py            # embed new events + upsert to Pinecone
```

### run.py flow
```python
def main():
    raw_events = []
    raw_events += fetch_eventbrite()
    raw_events += scrape_uncoverla()
    # raw_events += fetch_instagram()   # stretch

    enriched = [enrich_with_llm(e) for e in raw_events]
    new_events = upsert_to_supabase(enriched)  # returns only newly inserted rows
    embed_and_upsert_to_pinecone(new_events)
```

### Scheduling
Use GitHub Actions — free, reliable, no infra to manage:
```yaml
# .github/workflows/ingest.yml
on:
  schedule:
    - cron: '0 */3 * * *'  # every 3 hours
jobs:
  ingest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
      - run: pip install -r requirements.txt
      - run: python -m ingestion.run
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          PINECONE_API_KEY: ${{ secrets.PINECONE_API_KEY }}
          EVENTBRITE_TOKEN: ${{ secrets.EVENTBRITE_TOKEN }}
```

### LLM enrichment prompt structure
```python
SYSTEM_PROMPT = """
You are an event taxonomy extractor for TappedIn.
Given a raw event (title, description, venue), output JSON with:
  category: one of [Music, Food & Drink, Art & Culture, Nightlife, Comedy, Wellness, Networking]
  tags: subset of [outdoor, indoor, 21+, family-friendly, limited-spots, pop-up, free-perks]
  vibe_tags: subset of [chill, energetic, intimate, social, creative, hyped, educational]
Output strict JSON only. No prose.
"""
```
Use `gpt-4o-mini` — about $0.15 per 1000 events.

---

## 7. Open Questions / Decisions Needed

1. **Eventbrite API access** — does the public API still work, or do we need a paid partner account? Raphael to spike on Wednesday.
2. **Instagram scraping legality** — stick with Apify (paid but safer) or instaloader (free, risk of IG blocks)? Team discussion.
3. **How many events per ingestion run?** Suggest start with 50-100 to keep LLM costs low while validating pipeline.
4. **Handling stale events** — when an event's date passes, do we soft-delete or hard-delete? Suggest soft-delete with an `is_active` column.
5. **Dedupe key** — suggest `(source, source_id)` unique constraint in Postgres.


---

## 8. Stretch Goals (only if core pipeline lands by Friday)

- Instagram popup scraping
- ElasticSearch for advanced filter queries
- Redis cache on hot event queries
- Event detail page
- Save/unsave event functionality
