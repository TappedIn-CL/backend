import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import json
import hashlib
import uuid
from datetime import datetime
import requests
from bs4 import BeautifulSoup
from sqlalchemy import text
from openai import OpenAI

from db.session import SessionLocal
from app.models.event import Event
from app.utils.event_utils import deactivate_past_events
from scrapers.date_utils import is_current_or_future_event, parse_event_datetime
from app.utils.geocoding import geocode_address

headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def get_events_from_page(city_slug="ca--los-angeles", page=1):
    url = f"https://www.eventbrite.com/d/{city_slug}/events/?page={page}"
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    tag = soup.find("script", {"type": "application/ld+json"})
    if not tag or not tag.string:
        return []

    data = json.loads(tag.string)
    items = data.get("itemListElement", []) if data.get("@type") == "ItemList" else []

    events = []
    for entry in items:
        item = entry.get("item", {})
        loc = item.get("location") or {}
        addr = loc.get("address") or {}
        location_parts = [loc.get("name"), addr.get("streetAddress"), addr.get("addressLocality")]
        location = ", ".join(p for p in location_parts if p) or None

        events.append({
            "title": item.get("name"),
            "date": item.get("startDate"),
            "location": location,
            "description": item.get("description"),
            "url": item.get("url"),
        })
    return events


def classify_categories_with_openai(events):
    payload = [
        {"i": i, "title": e["title"], "description": e.get("description") or ""}
        for i, e in enumerate(events)
    ]
    prompt = f"""
You are classifying Eventbrite events into categories.

For each event below, return the single best-fit category from this exact list:
Music, Food & Drink, Arts, Nightlife, Comedy, Wellness, Networking, Sports, Family, Fashion, Other

Use Other only when none of the specific categories fit. Every event must be assigned one of these categories.

Events:
{json.dumps(payload, indent=2)}

Return only a JSON array of objects like [{{"i": 0, "category": "Music"}}] — one per event, same indices, no explanation.
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    raw = response.choices[0].message.content.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    results = json.loads(raw)
    return {r["i"]: r["category"] for r in results}


def save_events_to_db(events):
    """Save or update eventbrite events using PostgreSQL upsert on (source, source_id)."""
    print(f"  → parsed {len(events)} event(s)")
    db = SessionLocal()
    try:
        saved = 0
        skipped = 0

        for e in events:
            if not e.get("title") or not e.get("date"):
                print(f"    ✗ skipped (missing title/date): {e.get('title')}")
                skipped += 1
                continue

            try:
                date = parse_event_datetime(e["date"])
            except ValueError as ex:
                print(f"    ✗ bad date '{e['date']}' for '{e['title']}': {ex}")
                skipped += 1
                continue

            if not is_current_or_future_event(date):
                print(f"    ✗ skipped past event: {e['title']} ({e['date']})")
                skipped += 1
                continue

            # Stable source_id: prefer event URL (unique per eventbrite event),
            # fall back to title|date if URL missing.
            id_source = e.get("url") or f"{e['title']}|{e['date']}"
            source_id = hashlib.md5(id_source.encode()).hexdigest()

            lat = lng = None
            if e.get("location"):
                lat, lng = geocode_address(e.get("location"))

            insert_stmt = text("""
                INSERT INTO events
                    (id, title, description, date, cost, location, category,
                     special_tags, vibe_tags, source, source_id, created_at, latitude, longitude)
                VALUES
                    (:id, :title, :description, :date, :cost, :location, :category,
                     :special_tags, :vibe_tags, :source, :source_id, :created_at, :latitude, :longitude)
                ON CONFLICT (source, source_id) DO UPDATE SET
                    title = EXCLUDED.title,
                    description = EXCLUDED.description,
                    date = EXCLUDED.date,
                    cost = EXCLUDED.cost,
                    location = EXCLUDED.location,
                    category = EXCLUDED.category,
                    special_tags = EXCLUDED.special_tags,
                    vibe_tags = EXCLUDED.vibe_tags,
                    latitude = EXCLUDED.latitude,
                    longitude = EXCLUDED.longitude
            """)

            try:
                db.execute(insert_stmt, {
                    "id": uuid.uuid4(),
                    "title": e["title"],
                    "description": e.get("description"),
                    "date": date,
                    "cost": 0.0,
                    "location": e.get("location"),
                    "category": e.get("category"),
                    "special_tags": None,
                    "vibe_tags": None,
                    "source": "eventbrite",
                    "source_id": source_id,
                    "created_at": datetime.utcnow(),
                    "latitude": lat,
                    "longitude": lng,
                })
                print(f"    ✓ saved/updated: {e['title']}")
                saved += 1
            except Exception as ex:
                print(f"    ✗ error saving '{e.get('title')}': {ex}")
                skipped += 1

        db.commit()
        print(f"  → {saved} events saved/updated, {skipped} skipped")

        deactivated = deactivate_past_events(db)
        if deactivated > 0:
            print(f"  → Deactivated {deactivated} past event(s)")

        return saved
    finally:
        db.close()


def scrape_eventbrite(max_pages: int = 3) -> list[dict]:
    """Fetch eventbrite LA events across pages, classify categories, return list of dicts."""
    all_events = []
    for page in range(1, max_pages + 1):
        print(f"Fetching page {page}...")
        try:
            events = get_events_from_page(page=page)
            if not events:
                print("  → no events on page, stopping")
                break
            categories = classify_categories_with_openai(events)
            for i, e in enumerate(events):
                e["category"] = categories.get(i, "Other")
            all_events.extend(events)
        except Exception as ex:
            print(f"  → Error on page {page}: {ex}")
    return all_events


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "../.env"))
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    events = scrape_eventbrite()
    total = save_events_to_db(events)
    print(f"\nDone. Total events saved/updated: {total}")
