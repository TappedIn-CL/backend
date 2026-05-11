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


def get_article_links(category_url="https://uncoverla.com/category/los-angeles-events/"):
    response = requests.get(category_url, headers=headers)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    links = []
    for card in soup.select("article.post"):
        link_el = card.select_one("div.post-title h3 a")
        if link_el and link_el.get("href"):
            links.append(link_el["href"])
    return links


def get_article_text(url):
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    content = soup.select_one("div.post-content, div.entry-content")
    return content.get_text(separator="\n", strip=True) if content else ""


def extract_events_with_openai(article_url, article_text):
    prompt = f"""
You are extracting structured event data from an LA events article.

Article URL: {article_url}

Article text:
{article_text[:6000]}

Extract each individual event mentioned and return a JSON array. Each event object should have:
- "title": event name (string)
- "date": start date in ISO format YYYY-MM-DD (string, required — skip event if unknown)
- "time": time as a string like "7:00 PM" or null if not mentioned
- "location": venue name and/or address (string or null)
- "cost": numeric cost in dollars, 0 if free, null if not mentioned
- "description": 1-2 sentence description (string)
- "category": the single best-fit category from this exact list: Music, Nightlife, Sports, Food & Drink, Art & Culture, Comedy, Wellness, Networking. Pick the closest match even if no category is a perfect fit — every event must be assigned one of these eight.

Return only valid JSON, no explanation. Example:
[{{"title": "...", "date": "2026-04-25", "time": "7:00 PM", "location": "...", "cost": 0, "description": "...", "category": "Music"}}]
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )

    raw = response.choices[0].message.content.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw)


def save_events_to_db(events):
    print(f"  → OpenAI returned {len(events)} event(s)")
    db = SessionLocal()
    try:
        added = 0
        for e in events:
            if not e.get("title") or not e.get("date"):
                print(f"    ✗ skipped (missing title/date): {e}")
                continue

            exists = db.query(Event).filter(Event.title == e["title"]).first()
            if exists:
                print(f"    ✗ duplicate: {e['title']}")
                continue

            try:
                date = datetime.fromisoformat(e["date"])
                if e.get("time"):
                    try:
                        time = datetime.strptime(e["time"], "%I:%M %p")
                        date = date.replace(hour=time.hour, minute=time.minute)
                    except ValueError:
                        pass
            except ValueError as ex:
                print(f"    ✗ bad date '{e.get('date')}' for '{e.get('title')}': {ex}")
                continue

            event = Event(
                title=e["title"],
                description=e.get("description"),
                date=date,
                cost=e["cost"] if e.get("cost") is not None else 0.0,
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

    print("Fetching article links...")
    links = get_article_links()
    print(f"Found {len(links)} articles")

    total = 0
    for url in links:
        print(f"Processing: {url}")
        try:
            text = get_article_text(url)
            if not text:
                continue
            events = extract_events_with_openai(url, text)
            print(f"  → OpenAI extracted {len(events)} event(s)")
            added = save_events_to_db(events)
            print(f"  → {added} events saved")
            total += added
        except Exception as e:
            print(f"  → Error: {e}")

    print(f"\nDone. Total events saved: {total}")
