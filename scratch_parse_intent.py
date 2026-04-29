import json
import sys
from agent.nodes import parse_intent

# Change this prompt to test different inputs
PROMPT = "indoor events for date night within 10 miles and under 500 bucks on June 16th, I want to drink some alcohol and dance"

# Allow overriding from command line: python scratch_parse_intent.py "your prompt here"
query = sys.argv[1] if len(sys.argv) > 1 else PROMPT

state = {
    "query": query,
    "semantic_query": "",
    "filters": {},
    "query_vector": None,
    "candidate_events": [],
    "ranked_events": [],
    "response": None,
}

print(f"\nQuery: {query}\n")

result = parse_intent(state)

print(json.dumps({
    "semantic_query": result["semantic_query"],
    "filters": result["filters"],
}, indent=2))
