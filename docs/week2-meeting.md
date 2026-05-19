# Week 2 Meeting Notes — Apr 21

---

## Process and Habits

- All branches must go through pull requests into main. No more direct pushes to main.
- Commit messages must be descriptive. Use the format: area: what changed (example: frontend: wire AuthModal to supabaseClient, backend: add Event SQLAlchemy model). No more two-word commits.
- Every PR description must include what changed, why it changed, and how to test it. Summary, Changes, Test Plan.
- One PR per deliverable per subteam, not one per day.
- Team leads should schedule subteam meetings by Thursday to assign and review tasks.

---

## Leftover Week 1 Tasks (finish by Thursday)

- Aadarsh needs to wire the AuthModal on main to Shauns Supabase auth flow. The JWT user ID needs to connect to the backend GET /users/me endpoint so that when a user logs in their profile loads from Supabase.
- Joyce created a branch with the user model. Shaun needs to verify it and Joyce needs to open a PR to merge it into main.
- The backend event schema PR needs to be reviewed and merged. I will verify it once the PR is open. This is the highest priority item because everything else is blocked on it.
- Aadarsh also needs the useAuth hook to call GET /users/me after login and store the profile in context.
- Melinda needs to wire the search bar to hit the real GET /events endpoint on the backend instead of filtering a local array. Check commit 8ea3ee5 to confirm whether the mock event flow was implemented.
- The frontend landing page does not match the design lofis. This needs to be fixed as soon as possible. A joint frontend and design meeting is needed to align.
- Design presented landing page and auth flow lofis today. Frontend needs to implement those lofis. A separate meeting between frontend and design should happen this week.
- Design needs to finalize the event card component. Look at Eventbrite, Luma, Partiful, and Airbnb listings for inspiration.
- Once the event schema is merged, the AI team needs to implement the full end-to-end LangGraph flow using mock data. The frontend search query should be able to retrieve a hardcoded event from the backend. This needs to be done in the next two days.
- Design needs to have event page lofis ready for next week.

---

## Week 2 New Goal: Data Ingestion Pipeline

The goal is to build a pipeline that automatically pulls real LA events from external sources, enriches them with AI-generated tags, stores them in Supabase, and indexes them in Pinecone for semantic search.

The pipeline flow is:

- A GitHub Actions job runs every 3 hours
- It pulls events from the Eventbrite API and scrapes UncoverLA using BeautifulSoup
- Each raw event is passed through an LLM call (GPT-4o-mini) to extract category, tags, and vibe tags
- New events are upserted into Supabase using a source and source ID as a unique key to avoid duplicates
- New events are embedded using OpenAI and upserted into Pinecone for vector search

### Scope Cuts for Week 2

- Eventbrite API first. It is structured, free, and reliable. Prove the full pipeline with Eventbrite before touching scrapers.
- BeautifulSoup for one site only, UncoverLA. Add others in Week 3.
- Instagram scraping is a stretch goal. If it is not working by Friday, push it to Week 3.
- No ElasticSearch this week. Postgres and Pinecone are sufficient.
- No advanced geo queries yet. Use basic latitude and longitude math for now.

---

## Subteam Task Breakdown

### Backend

Priority 0 tasks:
- Merge event model PR and open GET /events, POST /events, and GET /events/{id} endpoints
- Joyce: merge user model PR with demographic fields
- Joyce: make sure GET /users/me returns the full user profile from the database, not just the JWT payload

Priority 1 tasks:
- Shaun: create the backend/ingestion/ folder with run.py, a sources/ folder, and enrichment.py
- Build the Eventbrite API client to pull LA events using venue.location.city=Los Angeles
- Build a BeautifulSoup scraper for the UncoverLA events page
- Shaun: set up the GitHub Actions workflow at .github/workflows/ingest.yml to run every 3 hours

Priority 2 tasks:
- Add deduplication logic using an upsert by source and source ID unique constraint in Postgres

### AI

Priority 0 tasks:
- Wire the retrieve_events node to real Pinecone instead of using MOCK_EVENTS
- Build the LLM enrichment function: takes a raw scraped event dict, returns normalized category, tags, and vibe_tags using the canonical enums listed below
- Build ingestion/embed.py: embed events using the build_embedding_text function and upsert vectors to Pinecone with metadata

LLM enrichment prompt instructions:
- Input: raw event with title, description, and venue
- Output: strict JSON only, no prose
- Category: one of Music, Food and Drink, Art and Culture, Nightlife, Comedy, Wellness, Networking
- Tags: subset of outdoor, indoor, 21+, family-friendly, limited-spots, pop-up, free-perks
- Vibe tags: subset of chill, energetic, intimate, social, creative, hyped, educational
- Model: gpt-4o-mini (approximately $0.15 per 1000 events)

Priority 1 tasks:
- Build the parse_intent node as a real LLM call that extracts price_max, date_range, tags_required, and distance from a natural language query
- Build the hydration step: after Pinecone returns event IDs, fetch the full event rows from Supabase

Priority 2 tasks:
- Apify or instaloader integration for Instagram popup accounts, starting with 5 to 10 curated accounts

### Frontend

Priority 0 tasks:
- Aadarsh: wire AuthModal to the real Supabase client (port from the auth branch)
- Aadarsh: useAuth hook calls GET /users/me after login and stores profile in context
- Melinda: wire the search bar to hit real GET /events?q= or the agent endpoint once it is ready
- Landing page must match the design lofis

Priority 1 tasks:
- Build the event feed page as a grid of event cards following the design spec
- Build the event card component with default, hover, and loading states per design
- Build the /profile page showing the users email and demographic data from /users/me

Priority 2 tasks:
- Melinda: build filter chips UI on the feed page for category, price, and date

### Design

Priority 0 tasks:
- Finalize the event card spec including default, hover, saved, and skeleton states
- Deliver event feed page lofis covering search bar, results grid, and filter chips

Priority 1 tasks:
- Joint session with frontend to align landing page with lofis
- Deliver agent query flow lofis covering the search bar, streaming response UI, and results view

Priority 2 tasks:
- Event detail page lofis for clicking into a card

---

## Open Questions

1. Does the Eventbrite public API still work for free, or do we need a paid partner account?
2. For Instagram scraping: Apify is paid but safer. Instaloader is free but risks account blocks. Which do we use?
3. How many events should we pull per ingestion run? Suggest starting with 50 to 100 to keep LLM costs low.
4. When an event date passes, do we soft-delete with an is_active column or hard-delete the row?
5. Dedupe key: use a unique constraint on source plus source_id in Postgres.
6. Do we need Elasticsearch or is Postgres plus Pinecone enough for now?

---

## Meeting Agenda

- Go over commit and PR habits with the full team
- Team leads schedule subteam meetings by Thursday to assign tasks
- Review leftover Week 1 tasks and emphasize that Aadarsh and Joyce need to get their branches merged into main this week
- Joint frontend and design discussion on implementing lofis (Shaun to lead)
- Go over open questions listed above

---

## Command to Test LangGraph End to End with Mock Data

Run this from the backend folder to verify the agent pipeline is working with hardcoded events:

cd /Users/rohanjadhav/TappedIn/backend && source venv/bin/activate && python -c "
from agent.graph import agent
result = agent.invoke({
    'query': 'chill outdoor event this weekend under \$20',
    'semantic_query': '',
    'filters': {},
    'query_vector': None,
    'candidate_events': [],
    'ranked_events': [],
    'response': None,
})
print('=== RESPONSE ===')
print(result['response'])
print()
print('=== RANKED EVENTS ===')
for i, e in enumerate(result['ranked_events'], 1):
    print(f\"{i}. {e['title']} — \${e['price_min']} — {e['venue_name']}\")
"
