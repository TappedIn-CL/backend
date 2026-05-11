import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import json
import requests
import hashlib
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
- "category": one of: Music, Food & Drink, Arts, Sports, Family, Fashion, Wellness, Nightlife, Other

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


def save_events_to_db(events, article_url):
    """Save or update events using PostgreSQL upsert on (source, source_id)."""
    print(f"  → OpenAI returned {len(events)} event(s)")
    db = SessionLocal()
    try:
        inserted = 0
        updated = 0
        skipped = 0
        
        for e in events:
            if not e.get("title") or not e.get("date"):
                print(f"    ✗ skipped (missing title/date): {e}")
                skipped += 1
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
                skipped += 1
                continue

            # Generate stable source_id from article URL + event title + date
            id_source = f"{article_url}|{e['title']}|{e['date']}"
            source_id = hashlib.md5(id_source.encode()).hexdigest()
            
            # Convert lists to comma-separated strings for storage
            special_tags_str = None
            if e.get("special_tags"):
                if isinstance(e["special_tags"], list):
                    special_tags_str = ",".join(e["special_tags"])
                else:
                    special_tags_str = e["special_tags"]
            
            vibe_tags_str = None
            if e.get("vibe_tags"):
                if isinstance(e["vibe_tags"], list):
                    vibe_tags_str = ",".join(e["vibe_tags"])
                else:
                    vibe_tags_str = e["vibe_tags"]

            # Use raw SQL for upsert with ON CONFLICT
            from sqlalchemy import text
            
            insert_stmt = text("""
                INSERT INTO events 
                    (id, title, description, date, cost, location, category, 
                     special_tags, vibe_tags, source, source_id, created_at)
                VALUES 
                    (:id, :title, :description, :date, :cost, :location, :category,
                     :special_tags, :vibe_tags, :source, :source_id, :created_at)
                ON CONFLICT (source, source_id) DO UPDATE SET
                    title = EXCLUDED.title,
                    description = EXCLUDED.description,
                    date = EXCLUDED.date,
                    cost = EXCLUDED.cost,
                    location = EXCLUDED.location,
                    category = EXCLUDED.category,
                    special_tags = EXCLUDED.special_tags,
                    vibe_tags = EXCLUDED.vibe_tags
            """)
            
            try:
                result = db.execute(insert_stmt, {
                    "id": __import__('uuid').uuid4(),
                    "title": e["title"],
                    "description": e.get("description"),
                    "date": date,
                    "cost": e.get("cost") if e.get("cost") is not None else 0.0,
                    "location": e.get("location"),
                    "category": e.get("category"),
                    "special_tags": special_tags_str,
                    "vibe_tags": vibe_tags_str,
                    "source": "uncoverla",
                    "source_id": source_id,
                    "created_at": datetime.utcnow(),
                })
                
                # Check if this was an insert or update by examining the rowcount
                # Note: On PostgreSQL, rowcount is 1 for both INSERT and UPDATE
                print(f"    ✓ {'updated' if db.execute(text(f'SELECT 1 FROM events WHERE source_id = :sid'), {'sid': source_id}).first() else 'saved'}: {e['title']}")
                inserted += 1  # Tracking both insert and update together
            except Exception as ex:
                print(f"    ✗ error saving '{e.get('title')}': {ex}")
                skipped += 1

        db.commit()
        print(f"  → {inserted} events saved/updated, {skipped} skipped")
        return inserted
    finally:
        db.close()


def run_scrape() -> int:
    """Scrape uncoverla, extract events with OpenAI, upsert into Supabase. Returns count."""
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
            added = save_events_to_db(events, url)
            print(f"  → {added} events saved/updated")
            total += added
        except Exception as e:
            print(f"  → Error: {e}")

    print(f"\nDone. Total events saved/updated: {total}")
    return total


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "../.env"))
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    run_scrape()
