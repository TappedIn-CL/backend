import os
os.environ['BACKEND_URL'] = 'http://localhost:8000'
from agent.nodes import hydrate_events

state = {
    'candidate_events': [
        #{'id': 'evt-001'},
        {'id': 'evt-001'},
    ],
}
result = hydrate_events(state)
print('Hydrated count:', len(result['hydrated_events']))
for e in result['hydrated_events']:
    print(f"  - {e.get('title')}: desc={bool(e.get('description'))}, vibes={e.get('vibe_tags')}")
