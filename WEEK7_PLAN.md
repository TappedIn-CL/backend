# TappedIn — Week 7 Plan

**May 27 → June 2, 2026** • **Theme:** Deploy, finish the W6 carryover, and stabilize for demo
**Mini-demo target:** Tuesday, June 2 (working end-to-end on a deployed URL — not localhost)
**Big Demo Day:** Week 10 (graphics due Mon, slides due Tue — see Announcements)

> **Notes for Rohan:** No new features this week. Every P0 below is W6 carryover plus deployment. Your personal critical-path items: ship the **AgentState extension first** so Jason isn't blocked, then `enrich_results`, then the place_id backfill (Charlton can't ship `open_now` without it). Once those land, focus shifts to deploying the backend on Render + frontend on Vercel and running real QA against the deployed URL, not localhost.

---

## 📣 Announcements (Read First)

1. **Monday Week 10 — Demo Day graphics due.** Design (Patrick + Nancy) closes out every remaining hi-fi. Anything not in Figma by Mon Week 10 EOD does not ship to demo.
2. **Tuesday Week 10 — Demo Day slides due** (for Wednesday iteration). All subteam leads contribute their slice; Rohan compiles.
3. **Deployment is THE deliverable this week.** No matter where we are on the W6 features, by Sunday June 1 EOD we must have: backend deployed on Render, frontend deployed on Vercel, prod Supabase migrated, prod Pinecone populated, real domain reachable from any browser.
4. **Bug bash Saturday May 30** — every subteam runs the deployed app end-to-end and files bugs in Discord `#bugs`. Triage Sunday morning.
5. **No new features this week.** If a teammate proposes scope creep, push back — point at this doc.

---

## 🎯 Week 7 Demo Goal

A teammate opens the **deployed URL** on their phone (not localhost), signs in with Supabase, and:

- Lands on the search page with three swipeable rails (Recommended for You / Recently Posted / Popular in LA), 5 cards each, no duplicate adjacent category artwork
- Browser prompts for location; coords flow into `/agent/query`
- Toggles **Happening Now** → list re-filters to events live right now (3h time window + `open_now` venue check)
- Types "chill rooftop bar right now" → SSE streams `parsing → retrieving → hydrating → enriching → scoring → justifying → results`
- Each card shows **transit time** ("18 min by transit") and a one-sentence agent **justification**
- Clicks **Going / Add to Calendar** → event lands on their in-app calendar and is auto-favorited
- Opens **Profile → Friends** → searches a teammate's username → sends a friend request → teammate accepts → sees the teammate's RSVP'd events
- Each event card on the For-You feed shows how many friends are going + a few friend avatars
- Clicks **Get Tickets** → opens the source website
- No past events appear anywhere in recommendations

Everything above must work on **the deployed URL**, not localhost. If it only works locally, it didn't ship.

---

## ⚙️ Process Reminders

- **Mini-demo Tuesday June 2.** Sunday May 31 night = integration deadline. Monday June 1 = bug fixes on deployed env only. No integration changes after Monday EOD.
- **Bug bash Saturday May 30** on the deployed URL.
- One joint integration sync this week (Frontend × AI × Backend × Design, 45 min) — schedule by Wednesday May 28.
- PRs only — no direct commits to `main`. Rebase before opening.
- **Branches with unmerged W6 work must merge by Wed May 28 EOD** so the rest of the team can build against them: `origin/user-demographics` (Joyce's RSVP), `origin/events` (Raphael's `website` field). Open the PRs today.
- Subteam standups by Wednesday May 28 EOD.
- Blocked? Surface in Discord within 5 minutes.
- **Carryover from W6 is P0 unless explicitly demoted.** No W6 feature gets dropped — we finish them.

---

## 🎬 Demo Flow

1. Open **deployed URL** (Vercel) on a phone
2. Sign in via Supabase Auth
3. Land on search page → three swipeable rails render with rotating artwork
4. Browser geolocation prompt → accept (`user_lat`, `user_lng` captured)
5. Toggle **Happening Now** → re-query with `happening_now: true`
6. Type "chill rooftop bar right now" → submit
7. SSE phases stream in: parsing → retrieving → hydrating → enriching → scoring → justifying → results
8. Cards render with transit time + justification + friend avatars + price + readable date + "Get Tickets" link
9. Click **Going / Add to Calendar** → toast confirms, event appears on user's calendar tab
10. Open **Profile** → tabs render in order: **Favorited Events / Calendar / Friends / Settings**
11. Click **Friends** → see friend grid → click "Add Friend" → search by username → send request
12. Other phone (teammate) accepts request → both refresh, see each other in friends list
13. Click a friend → see their calendar of "Going" events
14. Return to feed — event cards show "3 friends going" with avatar stack
15. Click **Get Tickets** on a card → opens source website in a new tab

---

## 🔍 Demo Scope

### Scope Cuts (stay cut)

- **Weather enrichment** — still deferred. Transit is the priority.
- **Multi-turn conversation** — still deferred. Confidence-based clarify is P2.
- **Google Calendar export / .ics** — still deferred. In-app calendar only.
- **Friend request notifications** — accept/deny flow only, no push/email notifications.
- **A/B personalization toggle**, **query-log dashboard UI**, **Instagram pipeline** — still deferred.

### Demo Non-Scope

Weather, multi-turn threaded chat, push notifications, calendar export/sync, A/B toggle, dashboard UIs, Instagram scraper, marker clustering, walking/driving toggle per card.

---

## 🧠 AI Subteam — Week 7 Tasks

| Priority | Task | Owner | Status |
|---|---|---|---|
| P0 | **CARRYOVER** Extend `AgentState` with `user_lat`, `user_lng`, `happening_now`, `time_intent`, `confidence`, `enriched_events`. **Ship Monday — everyone is blocked on this.** | Rohan | NOT STARTED |
| P0 | **CARRYOVER** `enrich_results` node — Distance Matrix from `user_lat/lng` to top-N venues, attach `transit_minutes` + `transit_mode`. Parallelize with `asyncio.gather` | Rohan | NOT STARTED (TODO already in `agent/tools.py`) |
| P0 | **CARRYOVER** Distance-aware scoring — `score *= 1 / (1 + miles / 10)` in `score_and_rank` | Rohan | NOT STARTED |
| P0 | **CARRYOVER** Place ID resolution — `venue_place_ids` table + backfill script (Places Text Search, cache forever). Blocks `open_now` | Rohan + Charlton | NOT STARTED |
| P0 | **CARRYOVER** Happening Now time filter — `start_time <= now AND (end_time >= now OR start_time + 3h >= now)` in `retrieve_events`; `parse_intent` emits `time_intent` | Rohan + Charlton | NOT STARTED |
| P0 | **CARRYOVER** `open_now` tool call — gated on `time_intent == "now"`, fan-out per candidate venue, Redis-cached | Charlton | NOT STARTED |
| P0 | **CARRYOVER** `justify` node — single batched LLM call, 1-sentence justification per top-N. Update graph topology to include enrich + justify | Allen | NOT STARTED |
| P0 | **CARRYOVER** `end_time` backfill / default — 3h blanket (or per-category: 3h concert / 2h comedy). Blocks Happening Now time filter | Allen | NOT STARTED |
| P0 | **NEW (deploy)** Remove past events from Pinecone — daily cleanup script that deletes vectors for events past their `end_time` / `start_time + 3h`. Keep rows in Supabase | Allen | NOT STARTED |
| P0 | **NEW (deploy)** End-to-end smoke test against the **deployed** backend after each Pinecone refresh | Allen | NOT STARTED |
| P1 | **CARRYOVER** Cross-source deduplication — fuzzy key (normalized title + date bucket + venue/geo proximity); dedup at ingest into Pinecone. Urgent with 9 sources live | Rohan | NOT STARTED |
| P1 | **CARRYOVER** `query_logs` table + writes on every `/agent/query` (query, filters, result_count, latency_ms, user_id) | Allen | NOT STARTED |
| P1 | **CARRYOVER** `score_breakdown` per event: `{query_sim, taste_sim, distance_penalty, final_score}` on `EnrichedEvent` | Charlton | NOT STARTED |
| P1 | **CARRYOVER** Friends recommendation signal — light boost in For-You ranking for events friends are RSVP'd to | Charlton | NOT STARTED |
| P1 | **NEW** Friend-event compatibility / overlap score — fuzzy key over friends' going + favorited events, surface "you might both like" | Rohan | NOT STARTED |
| P2 | **CARRYOVER** Confidence-based clarify node — `parse_intent` self-reports 0–1; new `clarify` node short-circuits to `END` with a follow-up question | Charlton | NOT STARTED |

---

## ⚡ Backend — Week 7 Tasks

| Priority | Task | Owner | Status |
|---|---|---|---|
| P0 | **NEW (deploy)** **Deploy backend to Render** — wire Procfile/start command, set every env var (`DATABASE_URL`, `OPENAI_API_KEY`, `PINECONE_API_KEY`, `PINECONE_INDEX`, `GOOGLE_MAPS_API_KEY`, `GOOGLE_PLACES_API_KEY`, `GEOCODING_API_KEY`, Supabase JWT secret, `REDIS_URL`), confirm SSE works through Render's proxy | Shaun | NOT STARTED |
| P0 | **NEW (deploy)** Run **all Alembic migrations on prod Supabase** (favorites, friendships, going_to_events, RSVPs, website, end_time, venue_place_ids, query_logs) | Shaun + Raphael | NOT STARTED |
| P0 | **NEW (deploy)** Trigger first full **prod Pinecone backfill** via the deployed cron — confirm all 9 scrapers run, enriched, embedded, upserted | Allen + Shaun | NOT STARTED |
| P0 | **NEW (deploy)** Update backend CORS allowlist for the **deployed frontend domain** (currently only `localhost:5173`/`:3000` in `app/main.py`) | Shaun | NOT STARTED (verified — only localhost in `app/main.py:23`) |
| P0 | **CARRYOVER** **Merge unmerged W6 branches by Wed EOD** — `origin/user-demographics` (Joyce's RSVP model + routes), `origin/events` (Raphael's `website` field). Open PRs today | Joyce, Raphael | DONE-ON-BRANCH (`d3efa5d`, `a375f20`) |
| P0 | **CARRYOVER** Rails endpoint — `GET /events/rails` returns `recommended_for_you` / `recently_posted` / `popular_in_la`. 5 per rail, max 20 on For-You, pagination cursor for swipe-to-next | Shaun | NOT STARTED |
| P0 | **CARRYOVER** Category-image rotation algorithm — return `image_variant` per event so no two adjacent cards in a rail share the same artwork | Shaun | NOT STARTED |
| P0 | **CARRYOVER** `/agent/query` accepts `user_lat`, `user_lng`, `happening_now` in the request body and threads them through `AgentState`. Add `enriching` + `justifying` phase events | Shaun | NOT STARTED (verified — `app/routers/agent.py:31` payload doesn't include these) |
| P0 | **CARRYOVER** Redis caching — `maps:distance:*`, `places:open_now:*`, `places:place_id:*`, `events:rail:*` with TTLs below. Required before demo, not optional | Shaun | NOT STARTED |
| P0 | **CARRYOVER** Remove past events from Pinecone (daily cron) — keep rows in Supabase | Raphael | IN PROGRESS (per Raphael's status report) |
| P0 | **CARRYOVER** Run **geocode backfill on prod Supabase** so markers + distance scoring use real coords, not 0.0 placeholders | Raphael | NOT STARTED (script exists at `scripts/backfill_event_coordinates.py`, not yet run against prod) |
| P0 | **NEW (deploy)** Friend request search/autocomplete endpoint — exists at `/users/search?q=` (Kyle shipped); verify performance with realistic user count, add username index if needed | Joyce | DONE-ON-MAIN (verified `app/routers/user.py:337`) but unverified for scale |
| P0 | **CARRYOVER** Add-to-Calendar UI hooks `POST /users/me/going-to` — Kyle's endpoints are live; smoke-test against the deployed env after deploy | Joyce | DONE-ON-MAIN (`app/routers/user.py:198`) |
| P1 | **NEW** Friend-event matching endpoint — `GET /users/me/friends/overlap` returning events both you and N friends are going to / have favorited | Joyce | NOT STARTED |
| P1 | **NEW** "Popular in LA" data source — denormalized counter on `events` for `favorites_count` + `going_count`, time-decayed scoring | Shaun + Joyce | NOT STARTED |
| P1 | **CARRYOVER** `scrapers/sources.py` registry — single list of active scrapers consumed by `run_pipeline.py` | Shaun | NOT STARTED |
| P1 | **CARRYOVER** Map free-filter bug — markers shouldn't default to free-only | Shaun + Melinda | NOT STARTED |
| P2 | **CARRYOVER** Quota guard — short-circuit `enrich_results` / `open_now` near Maps/Places limits, degrade gracefully | Shaun | NOT STARTED |
| P2 | **NEW (deploy)** Sentry / log aggregation on Render — at minimum, structured logging + a `/health` endpoint for uptime checks | Shaun | NOT STARTED |

---

## 🎨 Frontend — Week 7 Tasks

| Priority | Task | Owner | Status |
|---|---|---|---|
| P0 | **NEW (deploy)** **Deploy frontend to Vercel** — wire env vars (`VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`, `VITE_GOOGLE_MAPS_API_KEY`, **new** `VITE_API_BASE_URL` pointing at Render). Add `.env.example` while we're here | Jason | NOT STARTED |
| P0 | **NEW (deploy)** Replace hard-coded `http://localhost:8000` with `import.meta.env.VITE_API_BASE_URL` in **every** fetch site (agent SSE, /users/me, favorites, friends, going-to, events). Grep + audit | Jason + Aadarsh | NOT STARTED |
| P0 | **CARRYOVER** Geolocation capture — browser prompt on first `/agent/query`; attach `user_lat`/`user_lng` to request body. Fallback to UCLA coords on denial | Jason | NOT STARTED |
| P0 | **CARRYOVER** Happening Now toggle next to the search bar; flips `happening_now: true` on `/agent/query`. Style per design mid-fi | Jason + Melinda | NOT STARTED |
| P0 | **CARRYOVER** Three swipeable rails (Recommended / Recently Posted / Popular), 5 per rail, swipe to next page, rotating category artwork via `image_variant` from backend, max 20 on For-You | Kyle + Melinda | NOT STARTED |
| P0 | **CARRYOVER** Transit time on every event card — render `transit_minutes` + `transit_mode` ("18 min by transit"). Blocked on `enrich_results` shipping | Aadarsh | BLOCKED (waiting on Rohan's `enrich_results`) |
| P0 | **CARRYOVER** Render `justification` string under each card title. Blocked on `justify` node | Aadarsh | BLOCKED (waiting on Allen's `justify`) |
| P0 | **CARRYOVER** **Calendar view + "Going / Add to Calendar" button** — POST to `/users/me/going-to`; in-app calendar (month + list) renders RSVP'd events on correct dates; auto-favorite on RSVP | Aadarsh + Kyle | NOT STARTED (backend endpoints already exist) |
| P0 | **CARRYOVER** Profile page tab order: **Favorited Events / Calendar / Friends / Settings**, with counts under username | Kyle | NOT STARTED |
| P0 | **CARRYOVER** Friends panel — friend grid w/ avatars; click → friend's calendar; add-friend search w/ autocomplete (debounced calls to `/users/search?q=`); friend requests inbox with accept/deny | Kyle | NOT STARTED (all backend endpoints live in `app/routers/user.py`) |
| P0 | **CARRYOVER** Event card shows **friends-going count + first 4 friend avatars** | Kyle | NOT STARTED (needs backend `friends_going` join — assign Joyce to add) |
| P0 | **CARRYOVER** **"Get Tickets" button** wired to `event.website` (Raphael's field once merged) | Aadarsh | BLOCKED (merge `origin/events`) |
| P0 | **CARRYOVER** Fix map default filter — markers shouldn't default to free-only | Melinda | NOT STARTED |
| P0 | **CARRYOVER** Readable date formatting on event cards (currently rendering `2026-05-16T00:00:00`) | Aadarsh | NOT STARTED |
| P0 | **CARRYOVER** Loading animation for SSE phases (per Nancy's design) — phase-aware spinner, not a static loader | Jason | NOT STARTED |
| P0 | **CARRYOVER** Add loading state to favorites / calendar / friends tabs (currently flash empty before data arrives) | Aadarsh | NOT STARTED |
| P1 | **CARRYOVER** EventOverlay shows transit time + price block from enriched response | Aadarsh | BLOCKED on enrich |
| P1 | **CARRYOVER** Reasoning-trace expand — click justification to reveal `score_breakdown` (vibe / distance / taste) | Aadarsh | BLOCKED on `score_breakdown` |
| P1 | **CARRYOVER** Filter modal hard-filters the result list (distance, category, price) | Melinda | NOT STARTED |
| P1 | **CARRYOVER** Connect `price_min`/`price_max` to card UI (cards currently use placeholder price) | Aadarsh | NOT STARTED |
| P1 | **NEW (deploy)** Save button on full event detail saves to "going to" (not just favorites) | Aadarsh | NOT STARTED |

---

## 🖼️ Design Subteam — Week 7 Tasks

| Priority | Task | Owner | Status |
|---|---|---|---|
| P0 | **CARRYOVER** Close out remaining hi-fis for screens not finished in W6 (still owed) | Patrick + Nancy | IN PROGRESS |
| P0 | **CARRYOVER** Loading animation / "querying" symbol for SSE phases — still not built | Nancy | NOT STARTED |
| P0 | **NEW** Promote W6 mid-fis to hi-fi: add-friend / friend-requests page, Happening Now toggle states, profile tab order (Favorited / Calendar / Friends / Settings) | Patrick + Nancy | MID-FI DONE, NEEDS HI-FI |
| P0 | **NEW** Friend-event-card treatment — how the "3 friends going + avatars" stack renders | Patrick | NOT STARTED |
| P0 | **NEW** Deployed-app sanity — review the deployed Vercel app on real devices (iPhone Safari + Android Chrome) for layout breakage | Patrick + Nancy | NOT STARTED |
| P1 | **NEW** Demo Day graphics — start now; due Monday Week 10 | Patrick + Nancy | NOT STARTED |

---

## 🔗 Critical Path & Demo Dependency Chain

1. **Open the unmerged PRs today** — Joyce (RSVP), Raphael (website). Merge by Wed May 28 EOD.
2. **Rohan ships AgentState extension Monday** → unblocks Jason (request body), Charlton (`open_now`), Allen (`justify`), Aadarsh (transit on cards)
3. **Raphael runs geocode backfill on prod Supabase** → unblocks distance scoring + map markers
4. **Shaun puts every env var in Render** by Wednesday — including `GOOGLE_MAPS_API_KEY`, `GOOGLE_PLACES_API_KEY`, `REDIS_URL`
5. **Allen ships `end_time` default/backfill** → unblocks Happening Now time filter
6. **Rohan + Charlton ship place_id backfill** → unblocks `open_now`
7. **Rohan ships `enrich_results`** → unblocks Aadarsh's transit-on-cards + EventOverlay
8. **Allen ships `justify`** → unblocks Aadarsh's justification rendering
9. **Allen ships past-event cleanup script** → no stale events surface in demo
10. **Shaun deploys backend to Render with Redis** → frontend can point at a real URL
11. **Jason deploys frontend to Vercel + replaces hard-coded localhost** → app is reachable
12. **Saturday bug bash on deployed URL** → file in Discord
13. **Sunday triage + Monday fix-only on deployed env**
14. **Tuesday June 2: mini-demo on live URL** ✓

### Demo Blockers (Risk Order)

1. **Render + Vercel deployment** — net-new infra this week. Auth, CORS, SSE through a proxy, env-var sprawl. The biggest risk. Allocate **two full days**.
2. **The `place_id → open_now` chain** — same as W6. No place IDs → Happening Now degrades to a time filter. Backfill early.
3. **Real coordinates in prod** — distance scoring + transit + markers all need non-null lat/lng. Backfill must run on prod Supabase, not just locally.
4. **Maps/Places quota** — Distance Matrix + Places billed per call. Redis cache is mandatory before deploy, not after.
5. **`enrich_results` latency on deployed env** — Render free tier has cold starts. Transit calls add 1.5–3s on top of the ~6.8s baseline. Budget inside the `enriching` SSE phase; use `asyncio.gather` over top-N; cache aggressively.
6. **SSE through Render** — confirm Render's HTTP proxy keeps the connection open and doesn't buffer responses. Test early.
7. **Frontend env-var audit** — every hard-coded `localhost:8000` is a deploy bug waiting to happen. Grep and replace before Sunday.

---

## 🏗️ Architectural Details

### Target LangGraph Topology

```
parse_intent → retrieve_events → hydrate_events → compute_taste → score_and_rank → enrich_results → justify → END
```

**Current state (verified in `agent/graph.py`):** `parse_intent → retrieve → hydrate → compute_taste → score_and_rank → END`. No `enrich_results`, no `justify`. Both are W7 P0.

### Target AgentState

```python
class AgentState(TypedDict):
    query: str
    chips: list[str]
    user_profile: Optional[dict]
    user_lat: Optional[float]            # NEW (carryover)
    user_lng: Optional[float]            # NEW (carryover)
    happening_now: bool                  # NEW (carryover) — toggle from request body
    time_intent: Optional[str]           # NEW (carryover) — "now" | "today" | "weekend" | None
    confidence: Optional[float]          # NEW (carryover) — parse_intent self-report
    semantic_query: str
    filters: dict[str, Any]
    query_vector: Optional[list[float]]
    taste_vector: Optional[list[float]]
    candidate_events: list[EventSchema]
    hydrated_events: list[EventSchema]
    ranked_events: list[EventSchema]
    enriched_events: list[EnrichedEvent] # NEW (carryover) — top N with transit + justification + breakdown
    response: Optional[str]
```

**Current state (verified in `agent/state.py:24`):** none of the NEW fields exist yet.

### Distance Penalty (scoring)

```
miles = haversine(user_lat, user_lng, event.latitude, event.longitude)
score *= 1 / (1 + miles / 10)
```

### Happening Now (time filter)

```
start_time <= now AND (end_time >= now OR start_time + 3h >= now)
```

`open_now` is the **venue's** hours — only call it when `time_intent == "now"` and skip for ticketed events (concerts/festivals).

### Tables — Status

```
favorites (user_favorites)    ✅ on main
friendships                   ✅ on main (Kyle e41d59f) — uses requester_id/addressee_id + status
users.going_to_events         ✅ on main (Kyle e41d59f) — array column
events.website                🟡 on origin/events  (Raphael a375f20) — MERGE THIS WEEK
rsvps                         🟡 on origin/user-demographics (Joyce d3efa5d) — MERGE THIS WEEK
                                 (NOTE: Kyle's going_to_events array overlaps — decide which is canonical)
query_logs                    ❌ not built
venue_place_ids               ❌ not built
events.end_time backfill      ❌ not built (Allen's open question about pipeline scope)
```

**Decision needed in subteam sync:** Joyce's `rsvps` table vs Kyle's `users.going_to_events` array — pick one as the canonical RSVP store. Likely the `rsvps` table is the better long-term shape (it carries `created_at`, supports per-RSVP metadata, doesn't grow the user row); migrate the array reads/writes over and keep `going_to_events` as a read-through alias for one release.

### Redis Cache Keys

```
maps:distance:{origin_latlng}:{dest_latlng}:{mode}    TTL 24h
places:open_now:{place_id}                            TTL 15m
places:place_id:{normalized_venue_name}               TTL ∞
events:rail:{rail_name}:{user_id}:{page}              TTL 5m
```

### Deployment

- **Backend:** Render web service, Python 3.11, start cmd `uvicorn app.main:app --host 0.0.0.0 --port $PORT`. Free tier OK for demo; upgrade later. Add `redis-py` to requirements; use Render's managed Redis or Upstash.
- **Frontend:** Vercel, default Vite settings, env vars set in project dashboard, custom domain optional.
- **CORS:** add deployed frontend origin to `app/main.py:23` (currently only `localhost:5173`/`:3000`).
- **Auth:** Supabase project already exists; confirm redirect URLs include the Vercel domain.
- **SSE through Render:** verify the proxy doesn't buffer `text/event-stream`. If it does, swap to chunked or test with `--proxy-buffering off` equivalent.

---

## ❓ Open Questions

These all carry over from W6 — decide them this week so we can stop debating:

1. **Transit mode default** — `transit` always, or auto-pick (walking <1mi)?
2. **`open_now` for ticketed events** — skip for concerts (doors ≠ venue hours), apply only to bars/cafés/galleries?
3. **`end_time` default** — blanket 3h, or per-category (3h concert / 2h comedy)? Allen's question: is the per-scraper change worth the scope?
4. **Distance penalty divisor** — `/10` right for LA, or too aggressive?
5. **`rsvps` table vs `going_to_events` array** — pick one canonical store (see above).
6. **RSVP vs favorite** — strict superset (RSVP auto-favorites), or distinct states?
7. **"Popular in LA" rail** — by favorites, RSVPs, or both? Time-decayed how aggressively?
8. **Place ID backfill** — eager for all venues, or lazy + cache?
9. **Clarify node** — minimal confidence gate this week, or punt to Week 8?
10. **Image rotation pools** — fixed assets from design, or generated/tinted variants?
11. **NEW: Friend-event-matching score** — show on the card, or only in a friend's profile view?
12. **NEW: Render free tier** — accept cold starts for demo, or upgrade now?

---

## 🚀 Stretch Goals

Only if deployment is solid AND every W6 carryover P0 is shipped by Saturday EOD.

- Weather enrichment + forecast on EventOverlay
- Calendar export to Google Calendar / .ics
- Friend request push/email notifications
- Multi-turn refinement
- Marker clustering on map zoom-out
- "Why this event?" expanded hover justification
- Walking / driving / transit toggle per card
- AI friend-compatibility score visible on profile

---

## 🧪 AI Submeeting Tasks

- Lock `time_intent` schema + which categories get the `open_now` check (decision #2 above)
- Decide `enrich_results` N + whether transit runs inline or via `asyncio.gather` (default: gather, N=10)
- Pick the `justify` model (gpt-4o-mini for cost, or upgrade for quality?)
- Agree the cross-source dedup key (normalized title + date bucket + geo proximity within 100m)
- Place-ID backfill strategy — eager script over unique `venue_name` in Supabase, then lazy on miss
- Resolve `rsvps` vs `going_to_events` with Joyce + Kyle present
- Charlton: kick off place-ID backfill the moment Rohan's AgentState extension lands
- Allen: own the past-event cleanup cron + the post-deploy smoke test

---

## 💻 Test Commands

### LangGraph End-to-End (post-enrichment, post-justify)

```bash
python -c "
from agent.graph import build_graph
agent = build_graph()
result = agent.invoke({
    'query': 'chill rooftop bar right now',
    'chips': ['Chill'],
    'user_profile': {'interests': ['rooftops'], 'favorited_tags': ['chill']},
    'user_lat': 34.0689, 'user_lng': -118.4452,
    'happening_now': True, 'time_intent': None, 'confidence': None,
    'semantic_query': '', 'filters': {}, 'query_vector': None, 'taste_vector': None,
    'candidate_events': [], 'hydrated_events': [], 'ranked_events': [],
    'enriched_events': [], 'response': None,
})
for i, e in enumerate(result['enriched_events'], 1):
    print(f'{i}. {e[\"title\"]} - {e[\"transit_minutes\"]} min {e[\"transit_mode\"]}')
    print(f'   -> {e[\"justification\"]}  breakdown={e[\"score_breakdown\"]}')
"
```

### Streaming Endpoint with Happening Now + Geolocation — against DEPLOYED URL

```bash
curl -N -X POST https://tappedin-backend.onrender.com/agent/query \
  -H "Authorization: Bearer $JWT" -H "Content-Type: application/json" \
  -d '{"query": "chill rooftop bar right now", "chips": ["Chill"],
       "user_lat": 34.0689, "user_lng": -118.4452, "happening_now": true}'
```

### Rails

```bash
curl "https://tappedin-backend.onrender.com/events/rails?page=0" \
  -H "Authorization: Bearer $JWT"
```

### RSVP / Going-To + Friends (against deployed URL)

```bash
curl -X POST https://tappedin-backend.onrender.com/users/me/going-to?event_id=<uuid> \
  -H "Authorization: Bearer $JWT"

curl -X POST https://tappedin-backend.onrender.com/users/me/friends/request?user_id=<uuid> \
  -H "Authorization: Bearer $JWT"

curl -X POST https://tappedin-backend.onrender.com/users/me/friends/accept/<requester_id> \
  -H "Authorization: Bearer $JWT"

curl "https://tappedin-backend.onrender.com/users/search?q=charlton" \
  -H "Authorization: Bearer $JWT"
```

### Backfills (run against prod Supabase)

```bash
python -m scripts.backfill_event_coordinates    # existing events → real lat/lng
python -m ingestion.backfill_place_ids          # unique venue_name → place_id (NEW)
python -m ingestion.backfill_end_time           # default/per-category end_time (NEW)
python -m scripts.cleanup_pinecone_orphans      # remove past events from Pinecone
```

### Cache inspection (after Redis ships)

```bash
redis-cli -u $REDIS_URL KEYS "maps:distance:*" | head
redis-cli -u $REDIS_URL KEYS "places:open_now:*" | head
redis-cli -u $REDIS_URL KEYS "places:place_id:*" | head
redis-cli -u $REDIS_URL KEYS "events:rail:*" | head
```

### Health checks (after deploy)

```bash
curl https://tappedin-backend.onrender.com/health
curl https://tappedin-backend.onrender.com/                       # root → {"message": "TappedIn API running 🚀"}
curl -I https://tappedin.vercel.app                                # frontend reachable
```

---

## 📋 Plan Overview — Week 7 Kickoff Meeting

**Meeting structure:** Announcements → Carryover review → This week's focus → Subteam breakouts

### 1. Announcements (5 min)

- **Week 10 Demo Day**: graphics due Mon, slides due Tue (for Wed iteration). 3 weeks out — start design now.
- **Deployment is THE deliverable** this week. Demo must run on a public URL by Tue June 2.
- **Bug bash Sat May 30** on the deployed URL. Sunday triage. Monday = deploy-env fixes only.
- **No new features.** If anyone proposes one, this doc says no.

### 2. Carryover Review (15 min)

Read out W6 P0s that did **not** ship; assign each one to a named owner with a hard deadline:

- **AI:** `enrich_results`, `justify`, AgentState extension, Happening Now time filter, `open_now` tool call, place_id backfill, `end_time` backfill, distance-aware scoring, `score_breakdown`, friends-ranking signal, query_logs, cross-source dedup, confidence-clarify
- **Backend:** Rails endpoint, image-rotation algorithm, `/agent/query` accepting `user_lat/lng/happening_now`, Redis cache, Maps/Places env vars in Render, geocode backfill on prod, scrapers/sources.py registry, map free-filter bug, quota guard, **merge Joyce's RSVP PR**, **merge Raphael's website PR**
- **Frontend:** geolocation capture, Happening Now toggle, three swipeable rails, transit + justification on cards, calendar + Going button, profile tab order, friends panel + request flow + friend-avatar stack on cards, map default filter, readable dates, SSE loading animation, loading states for favorites/calendar/friends
- **Design:** remaining hi-fis, SSE loading animation, promote W6 mid-fis to hi-fi, friend-event-card treatment

### 3. This Week's Focus (10 min)

**One sentence:** deploy backend on Render, deploy frontend on Vercel, migrate prod, backfill prod, finish W6 carryover, bug bash Saturday, ship on Tuesday.

**Three things every owner does this week:**
- Land your W6 carryover task on **main** (not on a branch)
- Test it on the **deployed** URL, not localhost
- Participate in Saturday's bug bash

### 4. Decisions Needed in the Meeting (10 min)

- `rsvps` table vs `going_to_events` array — pick one
- Render free tier vs paid — accept cold starts or upgrade now
- Bug bash time Saturday (morning or evening?)
- Who owns the Render account + the Vercel account + which secrets store the keys

### 5. Subteam Breakouts (30 min)

Each subteam picks their own room and answers:
- Which carryover P0s are realistically shipping by Friday?
- Which need help from another subteam?
- What's the smoke-test plan against the deployed URL?

---

## Owner Snapshot

- **Rohan** — AgentState extension (ship Monday), `enrich_results` (transit), distance-penalty scoring, place_id backfill, cross-source dedup, friend-event compatibility score
- **Charlton** — `open_now` tool call, `score_breakdown`, friends signal in ranking, confidence-clarify (P2)
- **Allen** — `justify` node, `end_time` default/backfill, past-event cleanup cron, post-deploy smoke test, query_logs
- **Shaun** — **Render deploy + env vars + Redis**, rails endpoint + rotation, `/agent/query` body extension, CORS allowlist, quota guard, scrapers/sources.py
- **Joyce** — **merge RSVP PR**, friend-event overlap endpoint, friends-going-count join for cards
- **Raphael** — **merge website PR**, run geocode backfill on prod, past-event cleanup script
- **Jason** — **Vercel deploy**, env-var audit, geolocation capture, Happening Now toggle, SSE loading animation
- **Aadarsh** — transit + justification on cards, calendar / Going UI, EventOverlay enrichment, readable dates, "Get Tickets" wiring, loading states
- **Kyle** — three swipeable rails, profile tab order + counts, friends panel + request flow + friend-avatar stack on cards
- **Melinda** — map default-filter fix, rails layout polish, filter modal hard-filter
- **Patrick + Nancy** — finish remaining hi-fis, SSE loading symbol, promote mid-fis to hi-fi, friend-event-card design, **start Demo Day graphics**

---

**TappedIn • Week 7 • May 27 → June 2, 2026**
**Demo Day is Week 10 — start the slide deck Tuesday.**
