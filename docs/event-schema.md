# Event Schema — Backend / AI Handoff

**Author:** Rohan (AI team)
**For:** Raphael (Backend — Event model owner)
**Date:** Apr 15, 2026

This doc defines the canonical `Event` object for TappedIn. It covers how the event lives in Supabase (Postgres), how it's mirrored into Pinecone for vector search, and which fields the AI team uses to generate embeddings.

---

## 1. Summary of Ownership

- **Raphael (Backend):** Owns the full `Event` row in Postgres. Implements the SQLAlchemy model, Alembic migration, Pydantic schemas, and REST endpoints (`GET/POST /events`, `GET /events/{id}`).
- **AI team:** Owns the Pinecone index and the embedding function. Reads from Postgres, generates vectors, upserts into Pinecone. Does not modify the Postgres schema.

Postgres is the source of truth. Pinecone is a derived read-optimized index for semantic search.

---

## 2. The Event Object

Every event has these fields. All of them live in Postgres. A subset is embedded; a subset is also mirrored into Pinecone metadata.

| Field | Type | Purpose |
|---|---|---|
| `id` | UUID | Primary key |
| `source` | string | `"eventbrite"`, `"instagram"`, `"scraper"` |
| `source_id` | string | ID from the source system |
| `source_url` | string | Link back to original listing |
| `title` | string | Event name |
| `description` | text | Full event description |
| `category` | string | `"music"`, `"food"`, `"art"`, etc. |
| `tags` | string[] | `["free", "outdoor", "21+"]` |
| `vibe_tags` | string[] | `["chill", "energetic", "intimate"]` |
| `start_time` | datetime | When the event begins |
| `end_time` | datetime? | When it ends (nullable) |
| `venue_name` | string | e.g. "The Echo" |
| `address` | string | Full street address |
| `city` | string | e.g. "Los Angeles" |
| `latitude` | float | For map + distance filtering |
| `longitude` | float | For map + distance filtering |
| `price_min` | float | `0.0` = free |
| `price_max` | float | Upper bound of ticket price |
| `currency` | string | Default `"USD"` |
| `image_url` | string? | Event image (nullable) |
| `created_at` | datetime | Server-generated |
| `updated_at` | datetime | Server-generated (updates on write) |

---

## 3. Storage in Supabase (Postgres)

### SQLAlchemy Model

```python
# backend/app/models/event.py
from sqlalchemy import Column, String, Float, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.sql import func
import uuid

from db.session import Base


class Event(Base):
    __tablename__ = "events"

    # Identity
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source = Column(String, nullable=False)
    source_id = Column(String, nullable=False)
    source_url = Column(String, nullable=False)

    # Content
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    category = Column(String, nullable=False, index=True)
    tags = Column(ARRAY(String), nullable=False, default=list)
    vibe_tags = Column(ARRAY(String), nullable=False, default=list)

    # Time
    start_time = Column(DateTime(timezone=True), nullable=False, index=True)
    end_time = Column(DateTime(timezone=True), nullable=True)

    # Location
    venue_name = Column(String, nullable=False)
    address = Column(String, nullable=False)
    city = Column(String, nullable=False, index=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)

    # Money
    price_min = Column(Float, nullable=False, default=0.0)
    price_max = Column(Float, nullable=False, default=0.0)
    currency = Column(String, nullable=False, default="USD")

    # Media
    image_url = Column(String, nullable=True)

    # Bookkeeping
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

### Pydantic Schemas

```python
# backend/schemas/event.py
from datetime import datetime
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel


class EventBase(BaseModel):
    source: str
    source_id: str
    source_url: str
    title: str
    description: str
    category: str
    tags: List[str]
    vibe_tags: List[str]
    start_time: datetime
    end_time: Optional[datetime] = None
    venue_name: str
    address: str
    city: str
    latitude: float
    longitude: float
    price_min: float
    price_max: float
    currency: str = "USD"
    image_url: Optional[str] = None


class EventCreate(EventBase):
    pass


class EventResponse(EventBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
```

After merging, run `alembic revision --autogenerate -m "create events table"` and then `alembic upgrade head` to apply the migration.

---

## 4. Storage in Pinecone (AI team only — reference for context)

The AI team runs an ingestion job that reads new/updated rows from Postgres and upserts them into a Pinecone index (`tappedin-events`, 1536 dims, cosine similarity, serverless).

Each Pinecone record looks like:

```python
{
    "id": str(event.id),                  # same UUID as Postgres
    "values": embedding_vector,           # 1536-dim OpenAI embedding
    "metadata": {
        "start_time_unix": int(event.start_time.timestamp()),
        "latitude": event.latitude,
        "longitude": event.longitude,
        "price_min": event.price_min,
        "price_max": event.price_max,
        "city": event.city,
        "category": event.category,
    }
}
```

**Why only some fields in metadata?** Pinecone supports metadata filtering at query time. The AI team mirrors only what's needed for agent-driven filtering (date, distance, price, coarse bucketing). Everything else stays in Postgres and gets hydrated after the vector search returns candidate IDs.

Raphael does not need to implement anything here. The ingestion pipeline reads from the `events` table via SQLAlchemy.

---

## 5. Embedding Function (AI team owns — reference for context)

This function defines what text becomes the vector for each event. It lives in `backend/agent/embedding.py`.

```python
def build_embedding_text(event: Event) -> str:
    """
    Converts an Event into a string for OpenAI embedding.
    Changing this invalidates existing vectors — treat as a versioned contract.
    """
    return (
        f"{event.title}. "
        f"{event.description} "
        f"Category: {event.category}. "
        f"Tags: {', '.join(event.tags)}. "
        f"Vibe: {', '.join(event.vibe_tags)}. "
        f"Venue: {event.venue_name}."
    )
```

**Fields embedded:** `title`, `description`, `category`, `tags`, `vibe_tags`, `venue_name`
**Fields not embedded:** everything else (timestamps, coordinates, price, URLs, media)

The non-embedded fields are still in Postgres — they just aren't part of the semantic vector, because they describe *logistics*, not *meaning*. A user saying "chill rooftop under $20 this weekend" gets split into:

- Semantic: `"chill rooftop"` → matched against the vector
- Logistical: `price_max <= 20`, `date = this weekend` → matched against Pinecone metadata + Postgres columns

---

## 6. Filter Ownership at Query Time

| Endpoint | Filter layer | Owner |
|---|---|---|
| `GET /events?city=LA&max_price=20` (feed page) | Postgres SQL filter via SQLAlchemy | **Raphael** |
| `POST /agent/query "chill rooftop under $20"` (AI) | Pinecone metadata filter → Postgres hydrate | **AI team** |

Raphael only needs to support filtering on the REST endpoints (query params). The AI path uses its own filtering layer on top of Pinecone and does not go through Raphael's endpoints.

---

## 7. Open Questions to Sync On

1. **Valid category enum** — we should agree on a fixed set of category values (e.g., music, food, art, sports, nightlife, academic, popup, other) before the scraper starts writing data.
2. **Valid vibe tags** — same question for vibe tags; maybe a list of 10–15 canonical values we normalize to at ingestion time.
3. **Timezone handling** — proposing all timestamps stored as UTC in Postgres, converted client-side for display.

Let's lock these in by Friday so the scraper output and the event table agree.

---

## 8. Raphael's Action Items

1. Create `backend/app/models/event.py` with the SQLAlchemy model above.
2. Create `backend/schemas/event.py` with the Pydantic schemas above.
3. Run `alembic revision --autogenerate -m "create events table"` and `alembic upgrade head`.
4. Build `GET /events`, `POST /events`, `GET /events/{id}` endpoints.
5. Add mock events for frontend feed page testing.

Ping me (Rohan) once the table is live — AI team will then start building the Pinecone ingestion job against it.
