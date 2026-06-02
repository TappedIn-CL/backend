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


BASE_URL = "https://laist.com"
EVENTS_URL = f"{BASE_URL}/events"

headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}


def clean_text(value):
    value = html.unescape(str(value or ""))
    return re.sub(r"\s+", " ", value).strip()


def parse_json_ld_blocks(soup):
    blocks = []
    for script in soup.find_all("script", {"type": "application/ld+json"}):
        text = script.string or script.get_text(strip=True)
        if not text:
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        blocks.extend(data if isinstance(data, list) else [data])
    return blocks


def get_event_json_ld(soup):
    for block in parse_json_ld_blocks(soup):
        if isinstance(block, dict) and block.get("@type") == "Event":
            return block
    return {}


def normalize_title(title):
    return clean_text(title)


def normalize_location(location):
    if isinstance(location, list):
        location = location[0] if location else None
    if not isinstance(location, dict):
        return None

    address = location.get("address")
    parts = [location.get("name")]
    if isinstance(address, dict):
        parts.extend([
            address.get("streetAddress"),
            address.get("addressLocality"),
            address.get("addressRegion"),
            address.get("postalCode"),
            address.get("addressCountry"),
        ])
    elif address:
        parts.append(address)

    return clean_text(", ".join(part for part in parts if part)) or None


def source_id_from_url(url):
    path = urlparse(url).path.rstrip("/")
    event_slug = path.rsplit("/", 1)[-1]
    return event_slug if event_slug else hashlib.md5(path.encode()).hexdigest()


def is_current_or_ongoing(start_date, end_date=None, today=None):
    comparison_date = end_date or start_date
    return comparison_date.date() >= (today or date_cls.today())


def get_event_links(index_url=EVENTS_URL, max_pages=3):
    links = []
    seen = set()
    next_url = index_url
    visited_pages = set()

    for _ in range(max_pages):
        if not next_url or next_url in visited_pages:
            break

        visited_pages.add(next_url)
        response = requests.get(next_url, headers=headers, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        for link_el in soup.select(".EventList-LoadMore .EventPromo-LoadMore-title a[href]"):
            url = urljoin(BASE_URL, link_el["href"]).split("?")[0]
            if url in seen:
                continue
            links.append({
                "url": url,
                "title": clean_text(link_el.get_text(" ", strip=True)),
            })
            seen.add(url)

        load_more = soup.find("a", string=lambda value: value and "Load More" in value)
        next_href = load_more.get("href") if load_more else None
        next_url = urljoin(next_url, next_href) if next_href else None

    return links


def extract_description(soup, event_data):
    body = soup.select_one(".EventPage-articleBody")
    if body:
        lines = []
        for line in (clean_text(part) for part in body.get_text("\n", strip=True).splitlines()):
            if line:
                lines.append(line)
        description = "\n".join(lines)
        if description:
            return description[:1800]

    return clean_text(event_data.get("description"))[:1800] or None


def extract_cost(soup):
    price_el = soup.select_one(".EventPage-information-price")
    price_text = clean_text(price_el.get_text(" ", strip=True)) if price_el else ""
    if not price_text:
        return 0.0
    if re.search(r"\bfree\b|no cost|complimentary", price_text, re.I):
        return 0.0

    price_match = re.search(r"\$(\d+(?:\.\d{1,2})?)", price_text)
    return float(price_match.group(1)) if price_match else 0.0


def normalize_category(title, description):
    text = f"{title} {description}".casefold()
    if re.search(r"\b(cookbook|chef|food|culinary|cuisine|dinner|drink|restaurant)\b", text):
        return "Food & Drink"
    if re.search(r"\b(screening|film|documentary|museum|craft|art|creative|storytelling|storyslam|book|performance)\b", text):
        return "Arts"
    if re.search(r"\b(music|concert|dj|dance|rave|band)\b", text):
        return "Music"
    if re.search(r"\b(family|kids|children|multilingual readings)\b", text):
        return "Family"
    if re.search(r"\b(conversation|discussion|talk|panel|community)\b", text):
        return "Networking"
    if re.search(r"\b(soccer|dodger|sports)\b", text):
        return "Sports"
    return "Other"


def infer_special_tags(title, description, cost):
    text = f"{title} {description}".casefold()
    tags = []
    has_free_signal = re.search(r"\b(free admission|free event|free ticket|free tickets|rsvp for free)\b", text)
    if cost == 0.0 or has_free_signal:
        tags.append("Free perks")
    if "21+" in text or "venue is 21" in text:
        tags.append("21+")
    if any(word in text for word in ("family-friendly", "kid-friendly", "kids", "children")):
        tags.append("Family-friendly")
    if any(word in text for word in ("outdoor", "park", "museum of the american west")):
        tags.append("Outdoor")

    valid_tags = [tag for tag in tags if tag in ALLOWED_SPECIAL_TAGS]
    return ",".join(dict.fromkeys(valid_tags)) if valid_tags else None


def infer_vibe_tags(title, description):
    text = f"{title} {description}".casefold()
    tags = []
    if any(word in text for word in ("craft", "art", "creative", "storytelling", "book", "screening")):
        tags.append("Creative")
    if any(word in text for word in ("dance", "rave", "music", "dodger", "super-fun")):
        tags.append("Energetic")
    if any(word in text for word in ("conversation", "discussion", "community", "cookbook")):
        tags.append("Social")
    if any(word in text for word in ("family-friendly", "kid-friendly", "kids", "children")):
        tags.append("Chill")
    if any(word in text for word in ("talk", "panel", "documentary")):
        tags.append("Educational")

    valid_tags = [tag for tag in tags if tag in VIBE_TAGS]
    return ",".join(dict.fromkeys(valid_tags)) if valid_tags else None


def get_organizer(event_data):
    organizer = event_data.get("organizer")
    if isinstance(organizer, list):
        names = [
            clean_text(item.get("name"))
            for item in organizer
            if isinstance(item, dict) and item.get("name")
        ]
        return ", ".join(names) if names else None
    if isinstance(organizer, dict):
        return clean_text(organizer.get("name")) or None
    return None


def get_event_details(url):
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    event_data = get_event_json_ld(soup)
    title_el = soup.select_one(".EventPage-name")
    title = normalize_title(event_data.get("name") or (title_el.get_text(" ", strip=True) if title_el else None))
    start_date_raw = event_data.get("startDate")
    if not title or not start_date_raw:
        return None

    start_date = parse_event_datetime(start_date_raw)
    end_date = parse_event_datetime(event_data["endDate"]) if event_data.get("endDate") else None
    if not is_current_or_ongoing(start_date, end_date):
        return None

    description = extract_description(soup, event_data)
    source_url = event_data.get("mainEntityOfPage", {}).get("@id") or url
    if description and source_url not in description:
        description = f"{description}\n\nLAist source: {source_url}"

    cost = extract_cost(soup)
    category = normalize_category(title, description or "")
    if category not in ALLOWED_EVENT_CATEGORIES:
        category = "Other"

    return {
        "title": title,
        "description": description,
        "date": start_date.isoformat(),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat() if end_date else None,
        "cost": cost,
        "location": normalize_location(event_data.get("location")),
        "category": category,
        "special_tags": infer_special_tags(title, description or "", cost),
        "vibe_tags": infer_vibe_tags(title, description or ""),
        "source": "laist",
        "source_id": source_id_from_url(source_url),
        "source_url": source_url,
        "organizer": get_organizer(event_data),
    }


def scrape_laist(limit=None, max_pages=3):
    links = get_event_links(max_pages=max_pages)
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
    print(f"  -> extracted {len(events)} LAist event(s)")
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
                Event.source == "laist",
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
                "source": "laist",
                "source_id": source_id,
                "source_url": event_data.get("source_url"),
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
        print("No LAist events passed extraction.")
        return

    print(f"\nPreviewing {len(events)} extracted LAist event(s); nothing has been saved.")
    for index, event in enumerate(events, start=1):
        print(f"\n{index}. {event.get('title')}")
        print(f"   Date: {event.get('date')}")
        print(f"   Location: {event.get('location')}")
        print(f"   Category: {event.get('category')}")
        print(f"   Cost: {event.get('cost')}")
        print(f"   Tags: {event.get('special_tags') or ''}")
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
        f"URL: {event.get('source_url') or ''}",
    ]
    if event.get("description"):
        lines.extend(["", event["description"]])
    return "\n".join(lines)


def export_events_to_txt(events, output_path):
    content = [
        "LAist Events",
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
  <title>LAist Events</title>
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
  <h1>LAist Events</h1>
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
    parser = argparse.ArgumentParser(description="Scrape LAist events.")
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save extracted events to the database. By default, this only previews results.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit the number of event links processed.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=3,
        help="Maximum number of LAist listing pages to crawl.",
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

    events = scrape_laist(limit=args.limit, max_pages=args.max_pages)
    if args.output:
        export_events(events, args.output, args.format)
        print(f"\nWrote {len(events)} LAist events to {args.output}")
    elif args.save:
        total = save_events_to_db(events)
        print(f"\nDone. Total LAist events saved/updated: {total}")
    else:
        print_events_preview(events)
        print(f"\nDone. Total LAist events previewed: {len(events)}")
