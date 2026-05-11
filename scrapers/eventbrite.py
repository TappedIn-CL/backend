import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from openai import OpenAI

from db.session import SessionLocal
from app.models.event import Event

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
Music, Nightlife, Sports, Food & Drink, Art & Culture, Comedy, Wellness, Networking

Pick the closest match even if no category is a perfect fit — every event must be assigned one of these eight.

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
    print(f"  → parsed {len(events)} event(s)")
    db = SessionLocal()
    try:
        added = 0
        for e in events:
            if not e.get("title") or not e.get("date"):
                print(f"    ✗ skipped (missing title/date): {e.get('title')}")
                continue

            exists = db.query(Event).filter(Event.title == e["title"]).first()
            if exists:
                print(f"    ✗ duplicate: {e['title']}")
                continue

            try:
                date = datetime.fromisoformat(e["date"])
            except ValueError as ex:
                print(f"    ✗ bad date '{e['date']}' for '{e['title']}': {ex}")
                continue

            event = Event(
                title=e["title"],
                description=e.get("description"),
                date=date,
                cost=0.0,
                location=e.get("location"),
                category=e.get("category"),
            )
            db.add(event)
            print(f"    ✓ saving: {e['title']}")
            added += 1

        db.commit()
        return added
    finally:
        db.close()


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "../.env"))
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    total = 0
    for page in range(1, 4):
        print(f"Fetching page {page}...")
        try:
            events = get_events_from_page(page=page)
            if not events:
                print("  → no events on page, stopping")
                break
            categories = classify_categories_with_openai(events)
            for i, e in enumerate(events):
                e["category"] = categories.get(i, "Other")
            added = save_events_to_db(events)
            print(f"  → {added} events saved")
            total += added
        except Exception as e:
            print(f"  → Error: {e}")

    print(f"\nDone. Total events saved: {total}")
