# Embeddings in TappedIn

**Author:** Charlton Shih
**Last updated:** 2026-04-27

---

## What Is an Embedding?

An embedding is a list of numbers (a vector) that represents the *meaning* of a piece of text. Texts with similar meanings produce vectors that are mathematically close together. This is what makes semantic search possible — instead of matching exact keywords, you can find content that means the same thing even if it uses different words.

**Example:**
- "rooftop jazz bar" → `[0.12, -0.45, 0.88, ...]` (1536 numbers)
- "outdoor live music venue" → `[0.13, -0.44, 0.85, ...]` (very close)
- "dentist appointment" → `[0.91, 0.22, -0.67, ...]` (very far)

A user searching "outdoor live music venue" would surface the "rooftop jazz bar" event because their vectors are close — even though none of the words match.

---

## How TappedIn Uses Embeddings

TappedIn embeds two things:

| What | When | Function | Purpose |
|---|---|---|---|
| **Events** | During ingestion (scraping pipeline) | `embed_event(event)` | Index events in Pinecone so they're searchable |
| **User queries** | At search time (agent pipeline) | `embed_query(query)` | Find events that match what the user described |

Both use the same OpenAI model (`text-embedding-3-small`, 1536 dimensions) so that events and queries live in the same vector space and can be compared directly.

---

## What Gets Embedded

Not every field on an event is embedded — only fields that describe *meaning*. Logistics like price and date are better handled as hard filters.

### Event embedding text

```python
# agent/embedding.py — build_embedding_text()
f"{event['title']}. "
f"{event['description']} "
f"Category: {event['category']}. "
f"Tags: {', '.join(event['tags'])}. "
f"Vibe: {', '.join(event['vibe_tags'])}. "
f"Venue: {event['venue_name']}."
```

**Example output for a jazz event:**
```
Sunset Jazz at The Rooftop. Live jazz quartet at a converted warehouse 
rooftop with skyline views. Category: Music. Tags: outdoor, 21+. 
Vibe: chill, intimate. Venue: The Rooftop DTLA.
```

| Embedded (meaning) | Not embedded (logistics — used as filters instead) |
|---|---|
| title, description | start_time, end_time |
| category | price_min, price_max |
| tags, vibe_tags | latitude, longitude, address |
| venue_name | city |

### User query embedding

The user's raw or cleaned query is embedded as-is:

```python
# agent/embedding.py — embed_query()
embed_text("chill rooftop event this weekend under $20")
# → [1536-dim vector]
```

---

## The Embedding Pipeline (Ingestion Side)

When a new event is scraped and enriched by the LLM (Rohan's step), it flows into the embedding pipeline:

```
[Raw scraped event]
        │
        ▼ LLM enrichment (Rohan)
        │  fills in category, tags, vibe_tags
        ▼
ingestion/embed.py → embed_and_upsert(events)
        │  validates required fields are non-null
        ▼
agent/pinecone_client.py → upsert_events(events)
        │
        ├─ build_embedding_text(event)  ← formats the text to embed
        ├─ embed_event(event)           ← calls OpenAI, returns 1536 floats
        ├─ _build_record(event, vector) ← formats the Pinecone record
        └─ index.upsert(vectors=batch)  ← writes to Pinecone in batches of 100
```

### What gets stored in Pinecone

Each event in Pinecone has three parts:

```python
{
    "id": "evt-abc123",          # same UUID as the Postgres row
    "values": [0.12, -0.45, ...], # 1536-dim embedding vector
    "metadata": {
        # filterable fields (used for hard constraints at search time)
        "start_time_unix": 1746126000,
        "price_min": 15.0,
        "price_max": 15.0,
        "latitude": 34.04,
        "longitude": -118.23,
        "city": "Los Angeles",
        "category": "Music",
        "tags": ["outdoor", "21+"],

        # display fields (temporary — until Allen's hydration step is done)
        "title": "Sunset Jazz at The Rooftop",
        "venue_name": "The Rooftop DTLA",
    }
}
```

Only filterable fields and two temporary display fields (`title`, `venue_name`) live in Pinecone. All other display fields (description, address, image_url, source_url) are fetched from Supabase after the vector search returns IDs.

### Batching and retry

Pinecone has a batch size limit of 100 vectors per upsert call. For larger ingestion runs the pipeline chunks events into batches of 100 and retries each batch up to 4 times with exponential backoff (1s → 2s → 4s) before logging an error and continuing.

---

## The Query Pipeline (Search Side)

When a user types a query, the agent's `retrieve_events` node handles it:

```
User: "chill rooftop event this weekend under $20"
        │
        ▼ parse_intent (Allen's node)
        │  semantic_query: "chill rooftop"
        │  filters: { price_max: 20, start_time_unix: {$gte: ..., $lte: ...} }
        ▼
retrieve_events node (agent/nodes.py)
        │
        ├─ embed_query(semantic_query)      ← OpenAI → 1536-dim query vector
        └─ search_events(vector, filters)  ← Pinecone similarity search
                │
                └─ Pinecone finds the top 20 events whose vectors
                   are closest to the query vector, filtered by
                   price and date constraints
                        │
                        ▼
                candidate_events → score_and_rank → response
```

Pinecone uses **cosine similarity** to measure how close two vectors are. A score of 1.0 means identical meaning, 0.0 means completely unrelated.

---

## Why This Approach

**Why not just search by keywords?**

Keyword search fails when users describe things differently than how they're written. "Cheap outdoor vibes" would miss an event titled "Budget-Friendly Open-Air Experience." Embeddings capture the underlying meaning so these match.

**Why `text-embedding-3-small`?**

It's OpenAI's most cost-effective embedding model ($0.02 per 1M tokens), strong quality, and outputs 1536-dimensional vectors — the standard for Pinecone's cosine index. Upgrading to `text-embedding-3-large` later is a one-line change (and would invalidate all existing vectors, requiring a full re-embed).

**Why separate semantic fields from logistics?**

Blending "this Saturday at 8pm" into the embedding vector would make it drift toward time-related terms instead of content. Date and price are better handled as Pinecone metadata filters — they're applied before similarity ranking so they're a hard constraint, not just a suggestion.

**Why vibes as soft signals?**

Vibe tags (`chill`, `energetic`, `intimate`) are appended to the query text before embedding rather than used as hard metadata filters. AI-inferred vibes are fuzzy — hard-filtering on them would miss events that are clearly "chill" but weren't tagged that way. Soft signals let the vector do the fuzzy matching.

---

## Key Files

| File | What it does |
|---|---|
| `agent/embedding.py` | Core embedding functions: `build_embedding_text`, `embed_event`, `embed_query`, `embed_text` |
| `agent/pinecone_client.py` | Pinecone connection, `upsert_events` (ingestion), `search_events` (agent) |
| `ingestion/embed.py` | Pipeline step: validates events and calls `upsert_events` |
| `agent/nodes.py` | `retrieve_events` node: embeds query and calls `search_events` |

---

## Changing the Embedding Format

`build_embedding_text()` in `agent/embedding.py` is a **versioned contract**. Any change to how that string is formatted (adding a field, reordering, rewording) produces different vectors — meaning the new event vectors won't be comparable to existing ones in Pinecone.

If you need to change it:
1. Update `build_embedding_text()`
2. Re-run the full ingestion pipeline to re-embed all events
3. Old vectors in Pinecone become stale — either clear the index or accept mixed-quality results during the transition
