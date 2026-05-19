import os
from openai import OpenAI
from dotenv import load_dotenv
from agent.state import EventSchema

load_dotenv()

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMS = 1536

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _client


def build_embedding_text(event: EventSchema) -> str:
    """
    Converts an event into a single string for OpenAI embedding.
    Only semantic fields are included — logistics (price, date, coords) stay as filters.
    Changing this string format invalidates all existing Pinecone vectors.
    """
    return (
        f"{event['title']}. "
        f"{event['description']} "
        f"Category: {event['category']}. "
        f"Tags: {', '.join(event['tags'])}. "
        f"Vibe: {', '.join(event['vibe_tags'])}. "
        f"Venue: {event['venue_name']}."
    )


def embed_text(text: str) -> list[float]:
    """Embeds an arbitrary string using OpenAI. Used for both events and user queries."""
    response = _get_client().embeddings.create(
        model=EMBEDDING_MODEL,
        input=text,
    )
    return response.data[0].embedding


def embed_event(event: EventSchema) -> list[float]:
    """Embeds an event object. Convenience wrapper used by the ingestion pipeline."""
    return embed_text(build_embedding_text(event))


def embed_query(query: str) -> list[float]:
    """Embeds a user's natural language query for Pinecone similarity search."""
    return embed_text(query)
