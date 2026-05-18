from agent.embedding import embed_query
from agent.pinecone_client import search_events

vec = embed_query("chill outdoor music event")
results = search_events(vec, {}, top_k=5)
for m in results:
    title = m["metadata"].get("title", "?")[:60]
    cat = m["metadata"].get("category", "?")
    print(f"{m['score']:.3f}  {title}  ({cat})")
