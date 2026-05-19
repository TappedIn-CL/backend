from agent.pinecone_client import _get_index

r = _get_index().query(vector=[0.0]*1536, top_k=5, include_metadata=False)

for m in r['matches']:
    print(m['id'])
