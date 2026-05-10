# TappedIn Week 4 Plan

**May 5 → May 12** | Theme: Catch-up week. Demo target: **Tuesday May 12**.

> Notes for Rohan: change Pinecone login. Give Patrick interests and complete onboarding midfi.

---

## Week 4 Demo Goal

User types "I want a free outdoor event this weekend under $20" → ranked, scored list of real events streamed in real time alongside a non-interactive map placeholder. Auth, chips, personalization all working end-to-end on real data — no mocks.

---

## Process Reminders

- Demo is **Tuesday May 12**. Sunday night = integration deadline. Monday for live debugging. **No integration changes after Monday EOD.**
- One joint integration sync this week (Frontend × AI × Backend, 30–45 min).
- PRs only — no direct commits to main.
- Subteam standups by Wednesday EOD.
- Blocked? Surface in Discord within 5 minutes.

---

## Demo Flow

1. Sign in (Aadarsh + Kyle's auth — done)
2. Land on chat-style search page (Jason — done)
3. Click chips: `[Chill] [Outdoors]`
4. Type: "free event under $20 this weekend"
5. Submit → `POST /agent/query` (Shaun + Jason)
6. SSE phase events stream into thinking indicator (Allen + Nancy + Jason)
7. Final ranked event list renders alongside empty map placeholder (Jason + Patrick)
8. Click event → EventOverlay with hydrated data + vibe_tags badges (Aadarsh — done)

### Demo Scope Cuts

- Map = static placeholder (no Mapbox/Google Maps).
- No filter slide-out for demo.
- Save/unsave can stay localStorage-only if Joyce's favorites endpoint slips.
- No multi-turn conversations.
- No A/B personalization toggle.
- Streaming phase indicators are nice-to-have — fallback is single "Searching events..." spinner.

### Demo Non-Scope

Map interactivity, multi-turn, Instagram scraper, Partiful/DoLA scrapers, query log dashboard, hifi pass on landing/event/map, user testing.

---

## AI Subteam — Week 4 Tasks

| Priority | Task | Owner |
|---|---|---|
| P0 | Hydration node — batch-fetch full event rows via `GET /events/by-ids` | Allen |
| P0 | Migrate `parse_intent` to import from `agent/taxonomy.py`. Add `Sports` to categories, `adventurous` to vibes | Rohan |
| P0 | Wire full LangGraph: `parse_intent → retrieve_events → hydrate_events → compute_taste → score_and_rank → END`. Add `hydrated_events: list[EventSchema]` to `AgentState` | Rohan |
| P0 | Run enrichment.py over full Pinecone in one-off backfill | Charlton |
| P0 | **(NEW)** Move vibes out of Pinecone hard-filter → into `semantic_query` embedding | Rohan |
| P1 | Streaming wrapper — emit phase events using `graph.astream()` | Allen |
| P1 | `chip_mapping.py` shared frontend/backend | Rohan |
| P2 | Query logs + analytics | Allen |

---

## Backend — Week 4 Tasks

| Priority | Task | Owner |
|---|---|---|
| P0 | `POST /agent/query` SSE endpoint — calls LangGraph, streams phase + results | Shaun |
| P0 | `GET /events/by-ids` batch endpoint (promoted P1→P0) — blocks Allen's hydration | Raphael |
| P0 | User ↔ saved events relationship + `POST /users/me/favorites` | Joyce |
| P0 | `PATCH /users/me` for username/demographic updates | Joyce |
| P0 | Eventbrite scraper (reassigned Jason→Melinda) | Melinda |
| P0 | **(NEW)** Wire `user_profile` into agent request (JWT → `/users/me` → `AgentState.user_profile`) | Shaun |
| P1 | `GET /users/me` returns saved events | Shaun |
| P2 | `scrapers/sources.py` registry (demoted P1→P2) | Shaun |

---

## Frontend — Week 4 Tasks

| Priority | Task | Owner |
|---|---|---|
| P0 | Wire chat search bar to `POST /agent/query` with SSE consumption | Jason |
| P0 | Phase indicator + skeleton cards while streaming | Jason |
| P0 | Static map placeholder right of chat results | Melinda |
| P0 | EventOverlay reads real DB data instead of mocks | Aadarsh |
| P1 | Onboarding flow after account creation | Kyle |
| P1 | Save onboarding answers to profile + backend | Kyle |
| P1 | Update event card design to midfi spec (uniform sizes) | Aadarsh |
| P1 | Remove duplicate search bar on chat/results view | Aadarsh |
| P1 | Update Profile page layout to midfi | Kyle |
| P2 | Filter modal (price range, date, distance) | Melinda |
| P2 | "No exact matches" empty state | Melinda |

---

## Critical Path / Demo Dependency Chain

```
  ┌── Raphael: GET /events/by-ids ──────────┐
  ├── Charlton: enrichment backfill ────────┤
  ├── Rohan: parse_intent → taxonomy ───────┤
  └── Rohan: full graph wiring ─────────────┤
                                            ▼
                                Allen: hydration node
                                            │
                                            ▼
                            Shaun: POST /agent/query
                                            │
                                            ▼
                              Jason: SSE wiring (FE)
                                            │
                                            ▼
                                          DEMO
```

### Demo Blockers (in risk order)

1. Raphael's `/events/by-ids` — without this, hydration breaks.
2. Allen's hydration node — depends on (1).
3. Shaun's `POST /agent/query` — depends on (2). If not started by Wednesday, reassign.
4. Jason's SSE wiring — depends on (3).
5. Charlton's enrichment backfill — independent of API chain but determines whether events have tags.
6. Rohan's graph wiring + taxonomy migration — must land before Allen wires hydration into graph.

---

## Architectural Details

### `POST /agent/query` Request

```json
{
  "query": "free outdoor event this weekend under $20",
  "chips": ["Chill", "With Friends"]
}
```

### SSE Response Format

```
event: phase
data: {"phase": "parsing"}

event: phase
data: {"phase": "retrieving"}

event: phase
data: {"phase": "hydrating"}

event: phase
data: {"phase": "scoring"}

event: results
data: {"events": [...], "count": 10, "latency_ms": 1240}
```

### Final LangGraph Topology

```
parse_intent → retrieve_events → hydrate_events → compute_taste → score_and_rank → END
```

`compute_taste` runs **after** hydrate (not before retrieve) so it doesn't block Pinecone fetch. Charlton already wired it. Rohan inserts `hydrate_events` between `retrieve_events` and `compute_taste`.

### Final AgentState

```python
class AgentState(TypedDict):
    query: str
    chips: list[str]
    user_profile: Optional[dict]            # {"interests": [...], "favorited_tags": [...]}
    semantic_query: str
    filters: dict[str, Any]
    query_vector: Optional[list[float]]
    taste_vector: Optional[list[float]]     # computed by compute_taste node
    candidate_events: list[EventSchema]     # from Pinecone (sparse)
    hydrated_events: list[EventSchema]      # from Supabase (full rows)
    ranked_events: list[EventSchema]        # final ordered output
    response: Optional[str]
```

### Finalized 12-Chip Set

```
Chill, Hype, Creative, Adventurous,
Foodie, Music, Nightlife, Comedy, Wellness,
Solo, Date Night, With Friends
```

Mapping table → `agent/chip_mapping.py` (Rohan). Frontend imports same JSON contract.

---

## Open Questions

1. Map placeholder shape (gradient block, greyed map tile, lofi sketch?).
2. Demo auth — mentor logged in or anonymous? Who pre-seeds interests?
3. Cold-start scorer — seed mentor with realistic interests so 30% personalization kicks in?
4. Chip semantics — text appended to query string or separate `chips` list merged server-side?
5. Vibes filter — drop from filter dict, append to `semantic_query`. Confirm with Allen + Charlton.
6. Save/unsave path — (a) demo without, (b) localStorage shim, (c) stub backend route. **Recommend (b)**.
7. Phase indicator copy — "Parsing intent..." vs "Understanding your query..." vs none.
8. Eventbrite vs backfill — both P0, do not gate demo on Eventbrite.
9. Zero results — what does response string say?
10. Midterm fatigue — honest team check-in on availability.

---

## Stretch Goals (only if demo solid by Sunday)

- Joyce's favorites endpoint live and wired.
- Eventbrite scraper deduped in production.
- Allen's streaming wrapper emitting real phase events.
- Functional filter slide-out.
- Loading skeleton matches Nancy's hifi.
- Map placeholder upgraded to greyed-out city map image.

---

## AI Submeeting Tasks

- Taxonomy.py not connected to `agent/nodes.py` (Charlton).
- Hydration of Pinecone event data (Allen + Rohan).
- Fix `parse_intent` to append vibes to query, not embed as filter (Rohan).
- Change Pinecone login (Rohan).
- Wire hydration node into LangGraph (Rohan).
- Implement sorting + scoring algorithm for ranked events.
- SSE streaming service to frontend (Charlton + Rohan).
- Implement `chip_mapping.py` shared frontend/backend.
- Logging + Analytics → `query_logs` table (Charlton).

---

## Test Commands

### LangGraph end-to-end (post-hydration)

```bash
python -c "
from agent.graph import build_graph
agent = build_graph()
result = agent.invoke({
    'query': 'free outdoor event this weekend under \$20',
    'chips': ['Chill', 'With Friends'],
    'user_profile': {'interests': ['live music', 'rooftops'], 'favorited_tags': ['chill', 'outdoor']},
    'semantic_query': '',
    'filters': {},
    'query_vector': None,
    'taste_vector': None,
    'candidate_events': [],
    'hydrated_events': [],
    'ranked_events': [],
    'response': None,
})
print(result['response'])
for i, e in enumerate(result['ranked_events'], 1):
    print(f'{i}. {e[\"title\"]} — \${e[\"price_min\"]} — {e[\"venue_name\"]}')
"
```

### Streaming endpoint (post-Shaun)

```bash
curl -N -X POST http://localhost:8000/agent/query \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"query": "free outdoor event this weekend", "chips": ["Chill"]}'
```

### Hydration endpoint (post-Raphael)

```bash
curl "http://localhost:8000/events/by-ids?ids=uuid-1,uuid-2,uuid-3"
```

### Enrichment backfill (post-Charlton)

```bash
python -m ingestion.backfill_enrichment
```
