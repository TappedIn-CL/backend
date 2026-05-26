import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import argparse
import hashlib
import html
import json
import re
from datetime import date as date_cls
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from app.models.event import ALLOWED_EVENT_CATEGORIES, ALLOWED_SPECIAL_TAGS, VIBE_TAGS, Event
from app.utils.event_utils import enforce_coordinates_for_ingestion, is_event_active
from db.session import SessionLocal
from scrapers.date_utils import parse_event_datetime


BASE_URL = "https://partiful.com"
EXPLORE_URL = f"{BASE_URL}/explore/la"

headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}

TAG_CATEGORY_MAP = {
    "ARTS": "Arts",
    "COMMUNITY": "Networking",
    "FILM": "Arts",
    "FITNESS": "Wellness",
    "FOOD": "Food & Drink",
    "MUSIC": "Music",
}


def clean_text(value):
    value = html.unescape(str(value or ""))
    return re.sub(r"\s+", " ", value).strip()


def parse_next_data(soup):
    script = soup.select_one("#__NEXT_DATA__")
    if not script or not script.string:
        return {}
    try:
        return json.loads(script.string)
    except json.JSONDecodeError:
        return {}


def get_page_props(soup):
    return parse_next_data(soup).get("props", {}).get("pageProps", {})


def normalize_title(title):
    return clean_text(title)


def source_id_from_url(url):
    path = urlparse(url).path.rstrip("/")
    event_slug = path.rsplit("/", 1)[-1]
    return event_slug if event_slug else hashlib.md5(path.encode()).hexdigest()


def is_current_or_ongoing(start_date, end_date=None, today=None):
    comparison_date = end_date or start_date
    return comparison_date.date() >= (today or date_cls.today())


def event_url(event_id):
    return f"{BASE_URL}/e/{event_id}"


def normalize_location(location_info):
    if not isinstance(location_info, dict):
        return None

    parts = []
    display_name = clean_text(location_info.get("displayName"))
    if display_name:
        parts.append(display_name)

    display_lines = location_info.get("displayAddressLines") or []
    if display_lines:
        parts.extend(clean_text(line) for line in display_lines if clean_text(line))
    else:
        maps_info = location_info.get("mapsInfo") or {}
        parts.extend(clean_text(line) for line in maps_info.get("addressLines", []) if clean_text(line))
        approximate = clean_text(maps_info.get("approximateLocation"))
        if approximate and approximate not in parts:
            parts.append(approximate)

    return clean_text(", ".join(dict.fromkeys(part for part in parts if part))) or None


def normalize_category(tag_ids, title, description):
    priority_tag_ids = ["FOOD", "MUSIC", "FILM", "ARTS", "FITNESS", "COMMUNITY"]
    for tag_id in priority_tag_ids:
        if tag_id not in tag_ids:
            continue
        category = TAG_CATEGORY_MAP.get(tag_id)
        if category in ALLOWED_EVENT_CATEGORIES:
            return category

    text = f"{title} {description}".casefold()
    if re.search(r"\b(food|dinner|brunch|drink|cocktail|tasting|cooking|restaurant)\b", text):
        return "Food & Drink"
    if re.search(r"\b(concert|music|dj|dance|band|performance|party)\b", text):
        return "Music"
    if re.search(r"\b(film|movie|screening|art|gallery|craft|creative|book|workshop)\b", text):
        return "Arts"
    if re.search(r"\b(yoga|fitness|run|workout|wellness|meditation)\b", text):
        return "Wellness"
    if re.search(r"\b(comedy|stand[- ]?up|comic)\b", text):
        return "Comedy"
    if re.search(r"\b(network|meetup|community|social|mixer)\b", text):
        return "Networking"
    if re.search(r"\b(family|kids|children)\b", text):
        return "Family"
    if re.search(r"\b(fashion|beauty|style)\b", text):
        return "Fashion"
    return "Other"


def get_custom_section_text(event_data):
    sections = event_data.get("customSections") or []
    chunks = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        title = clean_text(section.get("title"))
        value = clean_text(section.get("value"))
        if title or value:
            chunks.append(": ".join(part for part in (title, value) if part))
    return "\n".join(chunks)


def extract_cost(event_data, description=""):
    ticketing = event_data.get("ticketing") or {}
    price = ticketing.get("price")
    if price not in (None, ""):
        try:
            return float(price)
        except (TypeError, ValueError):
            pass

    text = f"{description or ''}\n{get_custom_section_text(event_data)}"
    if re.search(r"\bfree\b|no cost|complimentary", text, re.I):
        return 0.0

    prices = []
    for match in re.finditer(r"\$(\d+(?:\.\d{1,2})?)", text):
        try:
            prices.append(float(match.group(1)))
        except ValueError:
            pass
    return min(prices) if prices else 0.0


def infer_special_tags(title, description, event_data, cost):
    text = f"{title} {description} {get_custom_section_text(event_data)}".casefold()
    tags = []
    has_free_signal = re.search(r"\b(free admission|free event|free show|free ticket|free tickets|free and open|open to all)\b", text)
    if cost == 0.0 and has_free_signal:
        tags.append("Free perks")
    if "21+" in text or "21 and over" in text:
        tags.append("21+")
    if any(word in text for word in ("family-friendly", "kid-friendly", "kids", "children")):
        tags.append("Family-friendly")
    if any(word in text for word in ("outdoor", "park", "rooftop", "garden", "beach")):
        tags.append("Outdoor")
    if event_data.get("enableWaitlist") or event_data.get("isCapped") or event_data.get("atCapacity"):
        tags.append("Limited spots")
    if any(word in text for word in ("pop-up", "popup", "pop up")):
        tags.append("Pop-up")

    valid_tags = [tag for tag in tags if tag in ALLOWED_SPECIAL_TAGS]
    return ",".join(dict.fromkeys(valid_tags)) if valid_tags else None


def infer_vibe_tags(title, description, category, tag_ids):
    text = f"{title} {description}".casefold()
    tags = []
    if category in {"Arts", "Fashion"} or "ARTS" in tag_ids:
        tags.append("Creative")
    if category in {"Music", "Nightlife", "Sports"} or any(word in text for word in ("party", "dance", "festival", "rave")):
        tags.append("Energetic")
    if category in {"Networking", "Food & Drink"} or "COMMUNITY" in tag_ids:
        tags.append("Social")
    if any(word in text for word in ("intimate", "cozy", "small group")):
        tags.append("Intimate")
    if any(word in text for word in ("family-friendly", "kid-friendly", "kids", "children")):
        tags.append("Chill")
    if any(word in text for word in ("class", "workshop", "learn", "educational", "panel", "talk")):
        tags.append("Educational")

    valid_tags = [tag for tag in tags if tag in VIBE_TAGS]
    return ",".join(dict.fromkeys(valid_tags)) if valid_tags else None


def get_hosts(page_props, event_data):
    hosts = page_props.get("hosts")
    if hosts is None:
        hosts = event_data.get("hosts") or event_data.get("owners") or []
    if not isinstance(hosts, list):
        return None

    names = [
        clean_text(host.get("name"))
        for host in hosts
        if isinstance(host, dict) and host.get("name")
    ]
    return ", ".join(dict.fromkeys(names)) if names else clean_text(event_data.get("hostName")) or None


def extract_explore_items(page_props):
    containers = [page_props.get("trendingSection") or {}]
    containers.extend(page_props.get("sections") or [])

    items = []
    for container in containers:
        if isinstance(container, dict):
            items.extend(container.get("items") or [])
    items.extend(page_props.get("feedItems") or [])
    return items


def event_from_payload(item):
    event_data = item.get("event") or {}
    event_id = event_data.get("id")
    title = normalize_title(event_data.get("title"))
    start_date_raw = event_data.get("startDate")
    if not event_id or not title or not start_date_raw:
        return None

    start_date = parse_event_datetime(start_date_raw)
    end_date = parse_event_datetime(event_data["endDate"]) if event_data.get("endDate") else None
    if not is_current_or_ongoing(start_date, end_date):
        return None

    tag_ids = [
        tag.get("id")
        for tag in item.get("tags", [])
        if isinstance(tag, dict) and tag.get("id") and tag.get("id") != "DISCOVER_HOME"
    ]
    description = clean_text(event_data.get("description"))[:1800] or None
    source_url = event_url(event_id)
    category = normalize_category(tag_ids, title, description or "")
    cost = extract_cost(event_data, description or "")

    return {
        "title": title,
        "description": description,
        "date": start_date.isoformat(),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat() if end_date else None,
        "cost": cost,
        "location": normalize_location(event_data.get("locationInfo")),
        "category": category,
        "special_tags": infer_special_tags(title, description or "", event_data, cost),
        "vibe_tags": infer_vibe_tags(title, description or "", category, tag_ids),
        "source": "partiful",
        "source_id": event_id,
        "source_url": source_url,
        "organizer": clean_text(event_data.get("hostName")) or None,
        "partiful_tags": tag_ids,
    }


def get_listing_events(index_url=EXPLORE_URL):
    response = requests.get(index_url, headers=headers, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    page_props = get_page_props(soup)

    events = []
    seen = set()
    for item in extract_explore_items(page_props):
        if not isinstance(item, dict) or item.get("type") != "event":
            continue
        event = event_from_payload(item)
        if not event or event["source_id"] in seen:
            continue
        events.append(event)
        seen.add(event["source_id"])
    return events


def get_event_details(event):
    url = event.get("source_url")
    if not url:
        return event

    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        page_props = get_page_props(soup)
    except Exception as ex:
        print(f"  -> detail fetch failed, using explore data: {ex}")
        return event

    event_data = page_props.get("event") or {}
    if not event_data:
        return event

    title = normalize_title(event_data.get("title")) or event["title"]
    description = clean_text(event_data.get("description"))[:1800] or event.get("description")
    if description and url not in description:
        description = f"{description}\n\nPartiful source: {url}"

    start_date = parse_event_datetime(event_data.get("startDate") or event["start_date"])
    end_date = parse_event_datetime(event_data["endDate"]) if event_data.get("endDate") else None
    if not is_current_or_ongoing(start_date, end_date):
        return None

    tag_ids = event.get("partiful_tags") or []
    category = normalize_category(tag_ids, title, description or "")
    cost = extract_cost(event_data, description or "")
    event.update({
        "title": title,
        "description": description,
        "date": start_date.isoformat(),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat() if end_date else None,
        "cost": cost,
        "location": normalize_location(event_data.get("locationInfo")) or event.get("location"),
        "category": category,
        "special_tags": infer_special_tags(title, description or "", event_data, cost),
        "vibe_tags": infer_vibe_tags(title, description or "", category, tag_ids),
        "organizer": get_hosts(page_props, event_data) or event.get("organizer"),
    })
    return event


def scrape_partiful(limit=None, enrich_details=True):
    listing_events = get_listing_events()
    if limit:
        listing_events = listing_events[:limit]

    events = []
    for index, event_data in enumerate(listing_events, start=1):
        print(f"Processing {index}/{len(listing_events)}: {event_data['source_url']}")
        try:
            event = get_event_details(event_data) if enrich_details else event_data
            if event:
                events.append(event)
                print(f"  -> extracted: {event['title']}")
            else:
                print("  -> skipped past or incomplete event")
        except Exception as ex:
            print(f"  -> Error: {ex}")
    return events


def save_events_to_db(events):
    print(f"  -> extracted {len(events)} Partiful event(s)")
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

            source_id = str(event_data["source_id"])
            existing = db.query(Event).filter(
                Event.source == "partiful",
                Event.source_id == source_id,
            ).first()

            values = {
                "title": event_data["title"],
                "description": event_data.get("description"),
                "date": event_date,
                "cost": event_data.get("cost") if event_data.get("cost") is not None else 0.0,
                "location": event_data.get("location"),
                "category": event_data.get("category") if event_data.get("category") in ALLOWED_EVENT_CATEGORIES else "Other",
                "special_tags": event_data.get("special_tags"),
                "vibe_tags": event_data.get("vibe_tags"),
                "source": "partiful",
                "source_id": source_id,
                "is_active": is_event_active(event_date),
            }

            values, skip_reason = enforce_coordinates_for_ingestion(values)
            if skip_reason:
                print(f"    x skipped missing coordinates ({skip_reason}): {event_data.get('title')}")
                skipped += 1
                continue

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
        print("No Partiful events passed extraction.")
        return

    print(f"\nPreviewing {len(events)} extracted Partiful event(s); nothing has been saved.")
    for index, event in enumerate(events, start=1):
        print(f"\n{index}. {event.get('title')}")
        print(f"   Date: {event.get('date')}")
        print(f"   Location: {event.get('location')}")
        print(f"   Category: {event.get('category')}")
        print(f"   Cost: {event.get('cost')}")
        print(f"   Tags: {event.get('special_tags') or ''}")
        print(f"   Organizer: {event.get('organizer') or ''}")
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
        f"Organizer: {event.get('organizer') or ''}",
        f"Partiful tags: {', '.join(event.get('partiful_tags') or [])}",
        f"URL: {event.get('source_url') or ''}",
    ]
    if event.get("description"):
        lines.extend(["", event["description"]])
    return "\n".join(lines)


def export_events_to_txt(events, output_path):
    content = [
        "Partiful LA Events",
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
        description = html.escape(event.get("description") or "").replace("\n", "<br>")
        source_url = html.escape(event.get("source_url") or "")
        tags = ", ".join(event.get("partiful_tags") or [])
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
            <dt>Organizer</dt><dd>{html.escape(event.get("organizer") or "")}</dd>
            <dt>Partiful tags</dt><dd>{html.escape(tags)}</dd>
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
  <title>Partiful LA Events</title>
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
  <h1>Partiful LA Events</h1>
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
    parser = argparse.ArgumentParser(description="Scrape Partiful LA explore events.")
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save extracted events to the database. By default, this only previews results.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit the number of events processed.",
    )
    parser.add_argument(
        "--skip-details",
        action="store_true",
        help="Use only the explore page payload and skip per-event detail requests.",
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

    events = scrape_partiful(limit=args.limit, enrich_details=not args.skip_details)
    if args.output:
        export_events(events, args.output, args.format)
        print(f"\nWrote {len(events)} Partiful events to {args.output}")
    elif args.save:
        total = save_events_to_db(events)
        print(f"\nDone. Total Partiful events saved/updated: {total}")
    else:
        print_events_preview(events)
        print(f"\nDone. Total Partiful events previewed: {len(events)}")
