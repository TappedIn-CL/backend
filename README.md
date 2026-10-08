# TappedIn

**An agentically powered event discovery platform for UCLA students.**

*Discover more, search less. Stay TappedIn.*

Built with [Creative Labs UCLA](https://creativelabsucla.com/).

---

## Overview

Los Angeles has one of the biggest event scenes in the country, from pop-ups in Sawtelle to immersive art shows in DTLA. But discovery is broken. Events are scattered across Instagram stories, Eventbrite pages, and word of mouth, and by the time you hear about something it is often over or sold out. Generic event sites also make it hard to search for specific requirements like budget, vibe, timing, and distance.

TappedIn fixes this in two ways:

1. **It aggregates events from many sources** (APIs, curated websites, and Instagram accounts) into one place.
2. **It lets you search in your own words.** Type something like *"Feeling nostalgic, find intimate and soulful house music now"* or *"I'm feeling thrifty and want some curated goods for cheap"*, and an AI agent finds, ranks, and explains the events that best match your intent and your personal taste.

Each result gets a **recommendation score** (shown as a percentage on the event card) and is plotted on an interactive map so you can check proximity at a glance.

---

## Features

### Landing page
- **AI search bar** for natural-language queries, with a "Happening Now" toggle
- **Mood pills** for one-tap vibes: Chill, Hype, Adventurous, Nightlife, Comedy, With Friends, Creative, Foodie, Cozy, Date Night, Music
- **Filters**: category, price range slider, free-events-only toggle, and a date range

### Search results
- **Chatbot interface** that returns recommended events with a short explanation of why each one fits
- **Interactive Google Map** with event markers and preview cards
- **Refine search** bar to adjust the query, map area, or mood without starting over

### For You page
- Curated rows: **Happening Now**, **Recommended for You**, **Recently Posted Events**, and **Popular Events in Los Angeles**
- **Event popup** with description, date and location, an embedded map, ticket link, "See who's going", add-to-calendar, and related recommendations

### Profile page
- **Favorites** (saved events), **Calendar** of upcoming events, **Friends**, and **Settings** (personal info and interests used to give the agent context)

---

## How It Works

TappedIn is a RAG-based agentic system: events are ingested and embedded into a vector database, and a LangGraph agent turns a user's natural-language request into a ranked, personalized list of events.

```mermaid
flowchart LR
    A[Event sources<br/>Eventbrite API, curated sites,<br/>Instagram accounts] --> B[Ingestion<br/>scrape + LLM extraction]
    B --> C[OpenAI embeddings<br/>1536-dim vectors]
    C --> D[(Pinecone<br/>vector DB)]
    B --> E[(PostgreSQL<br/>events + users)]
    F[User query] --> G[LangGraph agent<br/>parse intent]
    G --> D
    G --> E
    D --> H[Merge + score<br/>semantic + taste profile]
    E --> H
    H --> I[Ranked events<br/>+ recommendation score]
    I --> J[React frontend<br/>cards + Google Maps]
```

### 1. Data ingestion
Event data is pulled in on a recurring schedule from three kinds of sources:
- **Eventbrite API** for LA events
- **Web scraping (BeautifulSoup)** across a curated list of LA event and pop-up sites
- **Curated Instagram accounts** for UCLA and LA, scraped with Apify's Instagram scraper

Each ingested event goes through an **LLM extraction step** that reads the raw text or caption and pulls out structured details (title, date, time, location, price, category, vibe).

### 2. Processing and embeddings
Each normalized event is converted into a **1536-dimension embedding** using an OpenAI embedding model, based on its description and vibe, and upserted into the vector database. When a user clicks, likes, or attends an event, their taste profile is updated as well.

### 3. Storage
- **Pinecone** stores event vectors and user taste vectors. Cosine similarity between a query and an event's semantic meaning drives retrieval.
- **PostgreSQL** (via Supabase) stores relational and structured data: user profiles, saved and attended events, event metadata, and authentication data. It handles hard constraints such as time, price, and distance.

### 4. Agentic orchestration (LangGraph)
Instead of a simple sequential chain, the agent is a **LangGraph graph with conditional routing**:

1. **Parse intent**: the LLM extracts semantics and structured filters (event type, date, budget, vibe keywords) from the raw query.
2. **Retrieve**: semantic search in Pinecone runs alongside structured queries against the database; results are merged and deduplicated.
3. **Personalize**: candidates are compared against the user's taste profile (a centroid of their interaction history) to boost events that match their demonstrated preferences.
4. **Score and rank**: events receive a recommendation score combining semantic relevance to the query with the user's taste and event details such as price and distance.
5. **Return**: the top events come back with the score and a short justification.

### 5. Frontend
A React app renders the search experience, the chatbot, event cards, and the Google Maps view, and talks to the FastAPI backend. Users sign in, save events, build a calendar, and add friends.

---

## Tech Stack

| Layer | Technologies |
|---|---|
| **Frontend** | React, Google Maps API |
| **Backend** | FastAPI (Python), JWT-based auth |
| **Database** | PostgreSQL, Supabase |
| **AI / Agent layer** | LangGraph, OpenAI (LLM + embeddings), Pinecone |
| **Data ingestion** | BeautifulSoup, Eventbrite API, Apify (Instagram scraping) |
| **Design** | Figma |

---

## Planned / In Progress

These were part of the original project vision and may be partially built or on the roadmap:

- Tool calling to check **weather and transit time/cost** for each event, with a travel summary alongside the score (for example, "strong vibe match, free entry, 25 min by bus, clear skies Saturday")
- Agent follow-up questions mid-search when a query is ambiguous
- **Group planning** that accounts for the preferences of several friends
- Search and caching improvements (Elasticsearch, Redis) to cut API and LLM calls
- Containerized deployment and CI/CD (Docker, GitHub Actions)

---

## Design Process

The team moved from a **user flow** (feature ideation and an efficient path from landing page to event details to RSVP) to **lo-fi wireframes** to figure out screen and component layout, and then to **hi-fi mockups** that defined the final look: a warm peach-to-orange gradient and the TappedIn mascot.

---

## Team

**Project leads + manager:** Rohan, Shaun, Maahika

| Role | Members |
|---|---|
| Frontend | Kyle, Aadarsh, Melinda, Jason |
| Backend | Raphael, Joyce |
| AI / Agents | Charlton, Allen |
| Design | Taey, Nancy, Patrick |

---

## Acknowledgments

TappedIn was built as a Creative Labs UCLA project.

## Prerequisites

- **Python 3.11+**
- **PostgreSQL** — Supabase hosted DB (typical) or local Postgres
- **Supabase project** — same project as the frontend (auth + `public.users`)
- **Optional (agent / ingestion):** OpenAI API key, Pinecone index (`1536` dims, cosine)

---

## Quick start

```bash
cd backend

# 1. Virtual environment (once)
python3 -m venv venv
source venv/bin/activate

# 2. Dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 3. Environment
cp .env.example .env
# Edit .env with real values (see below)

# 4. Database schema
alembic upgrade head

# 5. Run API
uvicorn app.main:app --reload
```

- API: http://127.0.0.1:8000  
- Swagger: http://127.0.0.1:8000/docs  

**Important:** Always activate the venv before running `uvicorn`. If you see `ModuleNotFoundError: No module named 'langgraph'`, you are using system Python instead of `backend/venv`:

```bash
which python   # should end with backend/venv/bin/python
./venv/bin/uvicorn app.main:app --reload   # works without activating
```

---

## Environment variables

Copy `.env.example` → `.env` in the `backend` directory.

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | Postgres connection string (Supabase URI or local) |
| `SUPABASE_URL` | Yes* | Project URL, e.g. `https://xxxx.supabase.co` (no `/v1`) — JWT JWKS |
| `SUPABASE_ANON_KEY` | Yes* | Supabase anon key — sent when fetching JWKS |
| `OPENAI_API_KEY` | For agent / ingestion / scrapers | Embeddings and LLM enrichment |
| `PINECONE_API_KEY` | For agent | Vector search |
| `PINECONE_INDEX` | For agent | Default `tappedin-events` |
| `GOOGLE_MAPS_API_KEY` | Optional | Geocoding on `POST /events` |
| `BACKEND_URL` | Optional | Default `http://localhost:8000` (agent self-calls) |

\*Required for routes with `Authorization: Bearer <token>` (e.g. `/users/me/favorites`, `/agent/for-you`).

See **[.env.example](.env.example)** for the full template with comments.

**Example `.env` (Supabase):**

```env
DATABASE_URL=postgresql://postgres:[PASSWORD]@db.[PROJECT].supabase.co:5432/postgres
SUPABASE_URL=https://[PROJECT].supabase.co
SUPABASE_ANON_KEY=eyJ...
OPENAI_API_KEY=sk-...
PINECONE_API_KEY=pcsk_...
PINECONE_INDEX=tappedin-events
```

---

## Database migrations (Alembic)

Run from `backend` with venv active and `DATABASE_URL` set:

```bash
alembic upgrade head          # apply all migrations
alembic current               # show current revision
alembic history               # list revisions
```

After changing SQLAlchemy models:

```bash
alembic revision --autogenerate -m "describe your change"
alembic upgrade head
```

---

## API overview

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/` | No | Health / status |
| `GET` | `/events` | No | List upcoming events (`?q=` optional) |
| `GET` | `/events/by-ids` | No | Batch fetch by UUIDs (`?ids=`) |
| `GET` | `/events/{event_id}` | No | Single event |
| `POST` | `/events` | No | Create event (manual / admin) |
| `GET` | `/users/me` | JWT | Current user profile |
| `GET` | `/users/me/favorites` | JWT | Favorited events (hydrated) |
| `POST` | `/users/me/favorites` | JWT | Add favorite (`{ "event_id": "..." }`) |
| `DELETE` | `/users/me/favorites/{event_id}` | JWT | Remove favorite |
| `POST` | `/agent/query` | Optional JWT | SSE agent search |
| `GET` | `/agent/for-you` | JWT | Personalized recommendations |

Interactive docs: http://127.0.0.1:8000/docs

**Auth:** Send Supabase access token from the frontend:

```http
Authorization: Bearer <access_token>
```

Profile rows in `public.users` are created by your Supabase auth trigger on sign-up — there is no public `POST /users` register route on this API.

---

## Project layout

```text
backend/
├── app/
│   ├── main.py           # FastAPI app, CORS, routers
│   ├── models/           # SQLAlchemy (User, Event, UserFavorite)
│   ├── routers/          # events, users, agent
│   └── utils/
├── agent/                # LangGraph query + Pinecone retrieval
├── auth/                 # JWT verification (Supabase JWKS)
├── scrapers/             # Event ingestion per source
├── ingestion/            # LLM enrichment + embeddings
├── alembic/              # Migrations
├── db/                   # Engine + session
├── schemas/              # Pydantic request/response models
├── tests/
├── requirements.txt
└── .env                  # local only (not committed)
```

---

## Event ingestion (scrapers)

Run the full pipeline manually (scrape → enrich → embed):

```bash
source venv/bin/activate
python -m scrapers.run_pipeline
```

Sources are auto-discovered from `scrapers/*.py` modules that export `run_scrape()`. A GitHub Actions workflow can run this on a schedule in CI.

---

## CORS

Allowed local frontend origins (see `app/main.py`):

- http://localhost:5173  
- http://localhost:3000  

---

## Full-stack with frontend

1. Start backend (this README) on port **8000**.  
2. Start frontend from `../frontend` on port **5173** — see [frontend/README.md](../frontend/README.md).  
3. Ensure frontend `.env` Supabase keys match the same project as `SUPABASE_URL` / `DATABASE_URL` here.

---

## Troubleshooting

| Error | Fix |
|-------|-----|
| `ModuleNotFoundError: No module named 'langgraph'` | Activate `venv` or use `./venv/bin/uvicorn` |
| `Expected string or URL object, got None` | Set `DATABASE_URL` in `.env` |
| `503` / JWT errors on `/users/me/*` | Set `SUPABASE_URL` + `SUPABASE_ANON_KEY`; token must be a valid Supabase access token |
| Postgres connection refused | Check `DATABASE_URL`, VPN, Supabase IP allowlist |
| Alembic import errors | Run commands from `backend/` with venv active |

---

## Dependency management

Pinned deps live in `requirements.txt`. To add a top-level package:

```bash
pip install pip-tools
# edit requirements.in, then:
pip-compile requirements.in --output-file requirements.txt
pip install -r requirements.txt
```

---

## Related docs

- [Event schema (target)](docs/event-schema.md)
- [Agent architecture](docs/agent-architecture.md)
- [Project checklist](../docs/PROJECT_CHECKLIST.md)
