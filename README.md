# TappedIn Backend

FastAPI API for TappedIn: events, user profiles, favorites, and AI-powered search / recommendations (LangGraph + Pinecone).

**Stack:** Python 3.11+, FastAPI, SQLAlchemy, Alembic, PostgreSQL (Supabase), Supabase JWT auth, OpenAI, Pinecone.

---

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
