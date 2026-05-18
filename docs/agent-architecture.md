# TappedIn Agent Architecture

**Author:** AI team (Rohan, Charlton, Allen)
**Last updated:** Apr 21, 2026
**Audience:** Full team — frontend, backend, design, leadership

This doc explains how the TappedIn AI agent works end-to-end. It covers the pipeline shape, data flow, key technologies, and how each week of the roadmap builds on the last.

---

## 1. What the Agent Does

The agent takes a user's natural-language query (e.g. *"chill rooftop event this weekend under $20"*) and returns a ranked list of real LA events that semantically match the user's intent, filtered by hard constraints, and enriched with real-world context (weather, transit time, price).

The goal is simple: **discover more, search less.** A user shouldn't have to scroll through categories. They describe the vibe, and the agent finds it.

---

## 2. High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                           User's browser                              │
│               "I'm feeling thrifty, find curated finds"               │
└──────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼ POST /agent/query
┌──────────────────────────────────────────────────────────────────────┐
│                        FastAPI Backend                                │
│                                                                       │
│   ┌────────────────────────────────────────────────────────────┐     │
│   │            LangGraph Agent (backend/agent/)                 │     │
│   │                                                             │     │
│   │   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐  │     │
│   │   │ parse_intent │ → │  retrieve    │ → │  score_rank  │  │     │
│   │   │              │   │  _events     │   │              │  │     │
│   │   └──────────────┘   └──────────────┘   └──────────────┘  │     │
│   │         │                    │                   │          │     │
│   │         ▼                    ▼                   ▼          │     │
│   │    LLM (OpenAI)         Pinecone +           Tool calls    │     │
│   │    intent parsing       Postgres hydrate     (weather,     │     │
│   │                                               transit)      │     │
│   └────────────────────────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
                        Ranked events + justifications
                                    │
                                    ▼
                           Event cards + map pins
```

---

## 3. The Core Pipeline (3 Nodes)

The agent is implemented as a **LangGraph `StateGraph`** with three sequential nodes. Each node reads from and writes to a shared `AgentState` object.

### Node 1 — `parse_intent`
**Input:** raw user query string
**Output:** cleaned semantic text + structured filters

Uses an LLM (GPT-4o-mini) to translate fuzzy natural language into structured data:
- `"this weekend"` → `start_time_range: [Sat 00:00, Sun 23:59]`
- `"cheap"` → `price_max: 20`
- `"walking distance"` → `max_distance_miles: 1`
- `"outdoors"` → `tags_required: ["outdoor"]`

The remaining semantic content (`"chill rooftop jazz"`) is saved separately for vector search.

### Node 2 — `retrieve_events`
**Input:** semantic text + filters
**Output:** top-K candidate events

1. Embeds the semantic text via OpenAI (`text-embedding-3-small`, 1536 dims)
2. Queries Pinecone with the vector + metadata filters for hard constraints
3. Gets back candidate IDs + similarity scores
4. Hydrates each candidate from Postgres for full event details

### Node 3 — `score_and_rank`
**Input:** candidate events + user profile
**Output:** final ranked list + justification text

1. Re-scores candidates by blending vector similarity with the user's Pinecone taste profile (Week 8)
2. Invokes tools to enrich each event — weather, transit time, price validation (Week 7)
3. Generates a plain-English justification per event (*"Strong vibe match, free entry, 25 min by bus, clear skies Saturday"*)
4. Returns the top 5–10 events to the frontend

---

## 4. AgentState (Shared Whiteboard)

Every LangGraph node reads and writes the same typed state object. This is the single source of truth while a query is being processed:

```python
class AgentState(TypedDict):
    query: str                          # raw user input
    semantic_query: str                 # cleaned text for embedding
    filters: dict[str, Any]             # extracted structured filters
    query_vector: Optional[list[float]] # embedded semantic_query
    candidate_events: list[EventSchema] # top-K from Pinecone
    ranked_events: list[EventSchema]    # final scored list
    response: Optional[str]             # plain-English response
```

Think of it as a whiteboard — each node updates the parts it owns and passes the whole state forward.

---

## 5. Data Architecture

Three systems, each with a clear role:

| System | Role | What lives there |
|---|---|---|
| **Postgres (Supabase)** | Source of truth | Full event rows, user profiles, auth |
| **Pinecone** | Vector search index | Event embeddings + filterable metadata copy |
| **OpenAI** | Embeddings + LLM | `text-embedding-3-small`, GPT-4o-mini for intent |

**Postgres is authoritative.** Pinecone is a derived read-optimized index. The ingestion pipeline (Week 4) reads from Postgres, embeds events, and mirrors them into Pinecone.

### Pinecone Record Structure

```python
{
    "id": "<same UUID as Postgres events.id>",
    "values": [1536-dim embedding],
    "metadata": {
        "start_time_unix": int,
        "latitude": float, "longitude": float,
        "price_min": float, "price_max": float,
        "city": str, "category": str, "tags": [str]
    }
}
```

Only filterable fields go in metadata. Display fields (address, image_url, source_url) hydrate from Postgres after the vector search.

---

## 6. Embedding Strategy

Not every field on an event should go into the vector. We embed **meaning**, not **logistics**.

```python
def build_embedding_text(event: EventSchema) -> str:
    return (
        f"{event['title']}. "
        f"{event['description']} "
        f"Category: {event['category']}. "
        f"Tags: {', '.join(event['tags'])}. "
        f"Vibe: {', '.join(event['vibe_tags'])}. "
        f"Venue: {event['venue_name']}."
    )
```

| Embedded (describes meaning) | Not embedded (describes logistics) |
|---|---|
| title, description | start_time, end_time |
| category, tags, vibe_tags | latitude, longitude, address |
| venue_name | price_min, price_max |

The function is a **versioned contract** — changing it invalidates all existing Pinecone vectors. Any change requires a full re-embed.

---

## 7. Filter Strategy

Three kinds of filtering happen at query time:

### Hard filters (Pinecone metadata)
- Price, date, distance, city, category, special tags
- Applied as Pinecone `filter` argument → narrows the search space before similarity ranking
- User-facing: the filter chips in the UI

### Soft signals (added to the query vector)
- Vibe tags (chill, energetic, intimate...)
- Appended to the semantic query text before embedding
- Why: vibes are fuzzy — hard-filtering on AI-inferred vibes is brittle

### Natural language intent → filters
- User says *"cheap"* or *"tonight"* → `parse_intent` extracts `price_max`, `date_range`
- No manual filter click needed

### Example

```
User types:   "chill rooftop tonight under $20"
User clicks:  [Music] [21+]
        │
        ▼
parse_intent:
  semantic_query: "chill rooftop. Vibes: chill"
  filters: {
    category: "Music",             ← from UI click
    tags: ["21+"],                 ← from UI click
    price_max: 20,                 ← from "under $20"
    date_range: today_evening      ← from "tonight"
  }
        │
        ▼
Pinecone query:
  vector: embed("chill rooftop. Vibes: chill")
  filter: {
    category: "Music",
    tags: {"$in": ["21+"]},
    price_max: {"$lte": 20},
    start_time_unix: {"$gte": tonight_start, "$lte": tonight_end}
  }
  top_k: 20
```

---

## 8. User Taste Profile (Week 8)

Users also get a vector — their personal taste profile:

- **Onboarding** → tags embedded into a starting vector
- **Every like** → profile pulled toward that event's vector
- **Every dislike** → profile pushed away from that event's vector
- **Query time** → query vector blended with taste vector (e.g. 70% query, 30% taste)

This is how the agent "gets smarter the more you use it" — personalization without re-training any models.

---

## 9. Roadmap — How the Pipeline Fills In Week by Week

| Week | What gets built |
|---|---|
| **Week 1 (current)** | Folder scaffold, 3-node stub with mock data, Pinecone provisioned, embedding function signature |
| **Week 4** | Ingestion pipeline: scrape → Postgres → embed → Pinecone upsert |
| **Week 5** | `retrieve_events` wired to real Pinecone + ElasticSearch filters |
| **Week 6** | `parse_intent` becomes real LLM-based intent extraction. `POST /agent/query` endpoint live. Streaming responses. |
| **Week 7** | Tool calling — `weather_check`, `transit_time`, `distance_from_campus`. Justification text per event. |
| **Week 8** | User Pinecone taste profile + like/dislike updates. Personalized blending at query time. |
| **Week 9** | Redis caching on hot queries. End-to-end polish. |

---

## 10. File Structure

```
backend/agent/
├── __init__.py
├── state.py        EventSchema + AgentState TypedDicts
├── graph.py        LangGraph StateGraph definition
├── nodes.py        parse_intent, retrieve_events, score_and_rank
├── embedding.py    build_embedding_text, embed_text, embed_query, embed_event
└── tools.py        weather, transit, distance (Week 7 stubs)
```

The agent lives **inside** the backend repo — not a separate service — so FastAPI routes can import and call `agent.invoke()` directly.

---

## 11. Key Decisions & Rationale

| Decision | Why |
|---|---|
| LangGraph over raw chains | Explicit state, easier to reason about, supports parallel branches in later weeks |
| Pinecone over pgvector | Free tier generous, serverless, better filter performance at scale |
| OpenAI `text-embedding-3-small` (1536 dims) | Cost-effective ($0.02 / 1M tokens), strong quality, standard dim |
| Monorepo (agent inside backend) | No HTTP hop between backend and agent, simpler local dev |
| Vibes as soft filter (query text) | AI-inferred vibes are fuzzy — hard filtering is too brittle |
| Postgres as source of truth, Pinecone as derived | Standard CQRS-style split: write to one, read from the other |

---

## 12. Open Questions for Team Sync

1. **Category enum** — lock in the 7 values from design before the scraper ships (Music, Food & Drink, Art & Culture, Nightlife, Comedy, Wellness, Networking)
2. **Vibe tag enum** — finalize the 6–8 canonical vibes
3. **Special tag enum** — align on tags list (outdoor, indoor, 21+, family-friendly, limited spots, pop-up, free perks)
4. **Timezone policy** — proposing UTC in DB, client converts for display
5. **Streaming responses** — use SSE for agent responses in Week 6, or simple JSON? (recommendation: SSE)

---

## 13. Current State as of Apr 21

- ✅ `backend/agent/` scaffolded with all five files
- ✅ LangGraph pipeline compiled and running end-to-end with mock data
- ✅ Pinecone index `tappedin-events` created (1536 dims, cosine, serverless)
- ✅ OpenAI + Pinecone smoke test passing
- ✅ Event schema handed off to backend team
- ⬜ Sync with Raphael pending his Event model PR
- ✅ This doc

**Demo command** (runs the pipeline with mock data):
```bash
cd backend && source venv/bin/activate && python -c "
from agent.graph import agent
result = agent.invoke({
    'query': 'chill outdoor event this weekend under \$20',
    'semantic_query': '', 'filters': {},
    'query_vector': None, 'candidate_events': [],
    'ranked_events': [], 'response': None,
})
print(result['response'])
for e in result['ranked_events']: print(' -', e['title'])
"
```
