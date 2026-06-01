import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import argparse
import hashlib
import html
import json
import re
from datetime import date as date_cls
from datetime import datetime, time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from app.models.event import ALLOWED_EVENT_CATEGORIES, ALLOWED_SPECIAL_TAGS, VIBE_TAGS, Event
from db.session import SessionLocal
from scrapers.date_utils import parse_event_datetime


BASE_URL = "https://www.averagesocialite.com"
LA_EVENTS_URL = f"{BASE_URL}/los-angeles"

headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}

CATEGORY_MAP = {
    "art/culture": "Arts",
    "art + culture": "Arts",
    "awards": "Arts",
    "broadway": "Arts",
    "charity": "Networking",
    "comedy": "Comedy",
    "culinary": "Food & Drink",
    "family friendly": "Family",
    "fashion/beauty": "Fashion",
    "film/tv": "Arts",
    "free": "Other",
    "galas": "Networking",
    "literary": "Arts",
    "music": "Music",
    "sports": "Sports",
    "sports/fitness": "Wellness",
}

SPECIAL_TAG_MAP = {
    "free": "Free perks",
    "family friendly": "Family-friendly",
    "pop-up": "Pop-up",
    "popup": "Pop-up",
}

VIBE_TAG_MAP = {
    "art/culture": "Creative",
    "art + culture": "Creative",
    "culinary": "Social",
    "family friendly": "Chill",
    "fashion/beauty": "Creative",
    "music": "Energetic",
    "sports/fitness": "Energetic",
}

DESCRIPTION_STOP_PHRASES = (
    "Subscribe to our Free Newsletter",
    "CHECK OUR CALENDAR",
    "Posted in",
    "Earlier Event:",
    "Later Event:",
)


def clean_text(value):
    return re.sub(r"\s+", " ", value or "").strip()


def parse_json_response(raw):
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw)


def get_event_links(index_url=LA_EVENTS_URL):
    response = requests.get(index_url, headers=headers, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    links = []
    seen = set()
    for item in soup.select(".summary-item-record-type-event"):
        link_el = item.select_one(".summary-title-link[href], a[href*='/la-events/']")
        if not link_el:
            continue

        url = urljoin(BASE_URL, link_el["href"])
        if url in seen:
            continue

        title = clean_text(link_el.get_text(" ", strip=True) or link_el.get("aria-label"))
        date_text_el = item.select_one("time.summary-metadata-item--date")
        links.append({
            "url": url,
            "title": title,
            "date_text": clean_text(date_text_el.get_text(" ", strip=True)) if date_text_el else None,
        })
        seen.add(url)

    return links


def get_event_json_ld(soup):
    for script in soup.find_all("script", {"type": "application/ld+json"}):
        if not script.string:
            continue
        try:
            data = json.loads(script.string)
        except json.JSONDecodeError:
            continue

        candidates = data if isinstance(data, list) else [data]
        for candidate in candidates:
            if isinstance(candidate, dict) and candidate.get("@type") == "Event":
                return candidate
    return {}


def get_tags(soup):
    tags = []
    for tag_el in soup.select(".eventitem-meta-tags a"):
        tag = clean_text(tag_el.get_text(" ", strip=True))
        if tag:
            tags.append(tag)
    return tags


def normalize_category(tags, title, description):
    for tag in tags:
        category = CATEGORY_MAP.get(tag.casefold())
        if category in ALLOWED_EVENT_CATEGORIES:
            return category

    text = f"{title} {description}".casefold()
    if any(word in text for word in ("popup", "pop-up", "restaurant", "tasting", "pizza", "tea", "bbq")):
        return "Food & Drink"
    if any(word in text for word in ("premiere", "screening", "film", "art", "theatre", "museum")):
        return "Arts"
    if any(word in text for word in ("concert", "jazz", "music", "festival")):
        return "Music"
    if any(word in text for word in ("beauty", "fashion", "salon", "cosmetics")):
        return "Fashion"
    return "Other"


def normalize_tags(tags, mapping, allowed_tags):
    normalized = []
    for tag in tags:
        mapped = mapping.get(tag.casefold())
        if mapped in allowed_tags and mapped not in normalized:
            normalized.append(mapped)
    return ",".join(normalized) if normalized else None


def extract_cost(description):
    text = description.casefold()
    if re.search(r"\bfree\b|no cost|complimentary", text):
        return 0.0

    price_match = re.search(r"\$(\d+(?:\.\d{1,2})?)", description)
    if price_match:
        return float(price_match.group(1))
    return 0.0


def extract_description(soup):
    content = soup.select_one(".eventitem-column-content")
    if not content:
        return None

    text = content.get_text("\n", strip=True)
    for phrase in DESCRIPTION_STOP_PHRASES:
        index = text.find(phrase)
        if index != -1:
            text = text[:index]

    lines = []
    for line in (clean_text(part) for part in text.splitlines()):
        if not line:
            continue
        if line in {"Learn more", "When:", "Deets:", "Hint for the Average Socialite:", "What\u2019s Trending:"}:
            continue
        lines.append(line)

    return "\n".join(lines)[:1800] or None


def normalize_title(title):
    return clean_text(re.sub(r"\s+\u2014\s+Average Socialite$", "", title or ""))


def normalize_location(location):
    if not isinstance(location, dict):
        return None

    parts = [location.get("name"), location.get("address")]
    return clean_text(", ".join(part for part in parts if part))


def source_id_from_url(url):
    path = urlparse(url).path.rstrip("/")
    return hashlib.md5(path.encode()).hexdigest()


def is_current_or_ongoing(start_date, end_date=None, today=None):
    today = today or date_cls.today()
    comparison_date = end_date or start_date
    return comparison_date.date() >= today


def event_date_for_storage(start_date, end_date=None, today=None):
    if start_date.date() >= (today or date_cls.today()):
        return start_date
    if end_date and end_date.date() >= (today or date_cls.today()):
        return datetime.combine(today or date_cls.today(), time.min)
    return start_date


def get_event_details(url):
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    event_data = get_event_json_ld(soup)
    title_el = soup.select_one(".eventitem-title")
    title = normalize_title(event_data.get("name") or (title_el.get_text(" ", strip=True) if title_el else None))
    if not title:
        return None

    start_date_raw = event_data.get("startDate")
    if not start_date_raw:
        return None

    start_date = parse_event_datetime(start_date_raw)
    end_date = parse_event_datetime(event_data["endDate"]) if event_data.get("endDate") else None
    if not is_current_or_ongoing(start_date, end_date):
        return None

    tags = get_tags(soup)
    description = extract_description(soup)
    source_url = event_data.get("url") or url
    if description and source_url not in description:
        description = f"{description}\n\nAverage Socialite source: {source_url}"

    return {
        "title": title,
        "description": description,
        "date": event_date_for_storage(start_date, end_date).isoformat(),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat() if end_date else None,
        "cost": extract_cost(description or ""),
        "location": normalize_location(event_data.get("location")),
        "category": normalize_category(tags, title, description or ""),
        "special_tags": normalize_tags(tags, SPECIAL_TAG_MAP, ALLOWED_SPECIAL_TAGS),
        "vibe_tags": normalize_tags(tags, VIBE_TAG_MAP, VIBE_TAGS),
        "source": "averagesocialite",
        "source_id": source_id_from_url(url),
        "source_url": source_url,
        "tags": tags,
    }


def scrape_average_socialite(limit=None):
    links = get_event_links()
    if limit:
        links = links[:limit]

    events = []
    for index, link in enumerate(links, start=1):
        print(f"Processing {index}/{len(links)}: {link['url']}")
        try:
            event = get_event_details(link["url"])
            if event:
                events.append(event)
                print(f"  -> extracted: {event['title']}")
            else:
                print("  -> skipped past or incomplete event")
        except Exception as ex:
            print(f"  -> Error: {ex}")

    return events


def save_events_to_db(events):
    print(f"  -> extracted {len(events)} Average Socialite event(s)")
    db = SessionLocal()
    try:
        saved = 0
        skipped = 0

        for event_data in events:
            if not event_data.get("title") or not event_data.get("date"):
                print(f"    x skipped missing title/date: {event_data}")
                skipped += 1
                continue

            try:
                event_date = parse_event_datetime(event_data["date"])
            except ValueError as ex:
                print(f"    x bad date '{event_data.get('date')}' for '{event_data.get('title')}': {ex}")
                skipped += 1
                continue

            end_date_raw = event_data.get("end_date")
            try:
                event_end = parse_event_datetime(end_date_raw) if end_date_raw else None
            except ValueError:
                event_end = None

            source_id = str(event_data["source_id"])
            existing = db.query(Event).filter(
                Event.source == "averagesocialite",
                Event.source_id == source_id,
            ).first()

            values = {
                "title": event_data["title"],
                "description": event_data.get("description"),
                "date": event_date,
                "end_time": event_end,
                "cost": event_data.get("cost") if event_data.get("cost") is not None else 0.0,
                "location": event_data.get("location"),
                "category": event_data.get("category") if event_data.get("category") in ALLOWED_EVENT_CATEGORIES else "Other",
                "special_tags": event_data.get("special_tags"),
                "vibe_tags": event_data.get("vibe_tags"),
                "source": "averagesocialite",
                "source_id": source_id,
            }

            if existing:
                for key, value in values.items():
                    setattr(existing, key, value)
                print(f"    + updated: {event_data['title']}")
            else:
                db.add(Event(**values))
                print(f"    + saved: {event_data['title']}")
            saved += 1

        db.commit()
        print(f"  -> {saved} saved/updated, {skipped} skipped")
        return saved
    finally:
        db.close()


def print_events_preview(events):
    if not events:
        print("No Average Socialite events passed extraction.")
        return

    print(f"\nPreviewing {len(events)} extracted Average Socialite event(s); nothing has been saved.")
    for index, event in enumerate(events, start=1):
        print(f"\n{index}. {event.get('title')}")
        print(f"   Date: {event.get('date')}")
        print(f"   Location: {event.get('location')}")
        print(f"   Category: {event.get('category')}")
        print(f"   Cost: {event.get('cost')}")
        print(f"   Tags: {event.get('tags') or []}")
        print(f"   URL: {event.get('source_url')}")


def format_event_text(event, index):
    lines = [
        f"{index}. {event.get('title')}",
        f"Date: {event.get('date')}",
        f"Start: {event.get('start_date')}",
        f"End: {event.get('end_date')}",
        f"Location: {event.get('location') or ''}",
        f"Category: {event.get('category') or ''}",
        f"Cost: {event.get('cost')}",
        f"Special tags: {event.get('special_tags') or ''}",
        f"Vibe tags: {event.get('vibe_tags') or ''}",
        f"Average Socialite tags: {', '.join(event.get('tags') or [])}",
        f"URL: {event.get('source_url') or ''}",
    ]
    if event.get("description"):
        lines.extend(["", event["description"]])
    return "\n".join(lines)


def export_events_to_txt(events, output_path):
    content = [
        "Average Socialite LA Events",
        f"Exported: {datetime.now().isoformat(timespec='seconds')}",
        f"Count: {len(events)}",
        "",
    ]
    for index, event in enumerate(events, start=1):
        content.append(format_event_text(event, index))
        content.append("\n" + "-" * 80 + "\n")
    output_path.write_text("\n".join(content), encoding="utf-8")


def export_events_to_html(events, output_path):
    cards = []
    for index, event in enumerate(events, start=1):
        tags = ", ".join(event.get("tags") or [])
        description = html.escape(event.get("description") or "").replace("\n", "<br>")
        source_url = html.escape(event.get("source_url") or "")
        cards.append(f"""
        <article class="event">
          <h2>{index}. {html.escape(event.get("title") or "")}</h2>
          <dl>
            <dt>Date</dt><dd>{html.escape(event.get("date") or "")}</dd>
            <dt>Start</dt><dd>{html.escape(event.get("start_date") or "")}</dd>
            <dt>End</dt><dd>{html.escape(event.get("end_date") or "")}</dd>
            <dt>Location</dt><dd>{html.escape(event.get("location") or "")}</dd>
            <dt>Category</dt><dd>{html.escape(event.get("category") or "")}</dd>
            <dt>Cost</dt><dd>{html.escape(str(event.get("cost")) if event.get("cost") is not None else "")}</dd>
            <dt>Special tags</dt><dd>{html.escape(event.get("special_tags") or "")}</dd>
            <dt>Vibe tags</dt><dd>{html.escape(event.get("vibe_tags") or "")}</dd>
            <dt>Average Socialite tags</dt><dd>{html.escape(tags)}</dd>
          </dl>
          <p>{description}</p>
          <a href="{source_url}">Source</a>
        </article>
        """)

    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Average Socialite LA Events</title>
  <style>
    body {{
      font-family: Arial, sans-serif;
      line-height: 1.5;
      margin: 32px;
      max-width: 960px;
      color: #222;
    }}
    .event {{
      border-top: 1px solid #ddd;
      padding: 24px 0;
    }}
    h1, h2 {{
      line-height: 1.2;
    }}
    dl {{
      display: grid;
      grid-template-columns: 160px 1fr;
      gap: 6px 16px;
    }}
    dt {{
      font-weight: 700;
    }}
    dd {{
      margin: 0;
    }}
  </style>
</head>
<body>
  <h1>Average Socialite LA Events</h1>
  <p>Exported: {html.escape(datetime.now().isoformat(timespec="seconds"))}</p>
  <p>Count: {len(events)}</p>
  {''.join(cards)}
</body>
</html>
"""
    output_path.write_text(document, encoding="utf-8")


def export_events(events, output_path, output_format=None):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    output_format = output_format or output_path.suffix.lstrip(".").casefold()
    if output_format == "json":
        output_path.write_text(json.dumps(events, indent=2), encoding="utf-8")
    elif output_format == "html":
        export_events_to_html(events, output_path)
    elif output_format == "txt":
        export_events_to_txt(events, output_path)
    else:
        raise ValueError("Output format must be html, txt, or json.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape Average Socialite LA events.")
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save extracted events to the database. By default, this only previews results.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit the number of listing links processed.",
    )
    parser.add_argument(
        "--output",
        help="Write scraped events to an HTML, TXT, or JSON file without saving to the database.",
    )
    parser.add_argument(
        "--format",
        choices=("html", "txt", "json"),
        help="Output format. Defaults to the --output file extension.",
    )
    args = parser.parse_args()

    events = scrape_average_socialite(limit=args.limit)
    if args.output:
        export_events(events, args.output, args.format)
        print(f"\nWrote {len(events)} Average Socialite events to {args.output}")
    elif args.save:
        total = save_events_to_db(events)
        print(f"\nDone. Total Average Socialite events saved/updated: {total}")
    else:
        print_events_preview(events)
        print(f"\nDone. Total Average Socialite events previewed: {len(events)}")
