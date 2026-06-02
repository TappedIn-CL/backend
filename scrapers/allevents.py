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
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from app.models.event import ALLOWED_EVENT_CATEGORIES, ALLOWED_SPECIAL_TAGS, VIBE_TAGS, Event
from app.utils.event_utils import enforce_coordinates_for_ingestion, is_event_active
from db.session import SessionLocal
from scrapers.date_utils import parse_event_datetime


BASE_URL = "https://allevents.in"
POPUPS_URL = f"{BASE_URL}/los-angeles/pop-ups"

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


def get_listing_events(index_url=POPUPS_URL):
    response = requests.get(index_url, headers=headers, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    events_by_url = {}
    for block in parse_json_ld_blocks(soup):
        if isinstance(block, dict) and block.get("@type") == "Event" and block.get("url"):
            events_by_url[block["url"].split("?")[0]] = block

    for card in soup.select(".event-card-link[data-link]"):
        url = card["data-link"].split("?")[0]
        if url not in events_by_url:
            events_by_url[url] = {
                "@type": "Event",
                "name": card.get("data-name"),
                "url": url,
            }

    return list(events_by_url.values())


def normalize_title(title):
    return clean_text(title)


def normalize_location(location):
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
    event_id = path.rsplit("/", 1)[-1]
    return event_id if event_id else hashlib.md5(path.encode()).hexdigest()


def is_current_or_future(start_date, end_date=None, today=None):
    comparison_date = end_date or start_date
    return comparison_date.date() >= (today or date_cls.today())


def get_lowest_offer_price(offers):
    if isinstance(offers, dict):
        offers = [offers]
    if not isinstance(offers, list):
        return 0.0

    prices = []
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        for key in ("price", "lowPrice"):
            value = offer.get(key)
            if value in (None, ""):
                continue
            try:
                prices.append(float(value))
            except (TypeError, ValueError):
                pass
    return min(prices) if prices else 0.0


def infer_category(title, description):
    text = f"{title} {description}".casefold()
    if re.search(r"\b(food|breakfast|lobster|coffee|baked|drink)\b", text):
        return "Food & Drink"
    if re.search(r"\b(fashion|beauty|azazie|dress|dresses|outfit|bridal|bridesmaid)\b", text):
        return "Fashion"
    if re.search(r"\b(jewelry|craft|art|arts|exhibit|market|maker|handmade)\b", text):
        return "Arts"
    if re.search(r"\b(parenting|community|conversation|network)\b", text):
        return "Networking"
    return "Other"


def infer_vibe_tags(title, description):
    text = f"{title} {description}".casefold()
    tags = []
    if any(word in text for word in ("craft", "art", "jewelry", "exhibit", "maker")):
        tags.append("Creative")
    if any(word in text for word in ("community", "conversation", "market")):
        tags.append("Social")
    if any(word in text for word in ("family", "kids")):
        tags.append("Chill")
    valid_tags = [tag for tag in tags if tag in VIBE_TAGS]
    return ",".join(dict.fromkeys(valid_tags)) if valid_tags else None


def infer_special_tags(title, description, cost):
    text = f"{title} {description}".casefold()
    tags = ["Pop-up"]
    if cost == 0.0 or "free" in text:
        tags.append("Free perks")
    if "family" in text:
        tags.append("Family-friendly")
    valid_tags = [tag for tag in tags if tag in ALLOWED_SPECIAL_TAGS]
    return ",".join(dict.fromkeys(valid_tags)) if valid_tags else None


def extract_description(soup, event_data):
    content = soup.select_one(".event-description-html")
    if content:
        return clean_text(content.get_text(" ", strip=True))[:1800] or None
    return clean_text(event_data.get("description"))[:1800] or None


def merge_event_data(listing_data, detail_data):
    merged = dict(listing_data or {})
    for key, value in (detail_data or {}).items():
        if value not in (None, "", []):
            merged[key] = value
    return merged


def get_event_details(listing_data):
    url = listing_data.get("url")
    if not url:
        return None

    detail_data = {}
    description = clean_text(listing_data.get("description")) or None
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        detail_data = get_event_json_ld(soup)
        description = extract_description(soup, detail_data or listing_data) or description
    except Exception as ex:
        print(f"  -> detail fetch failed, using listing data: {ex}")

    event_data = merge_event_data(listing_data, detail_data)
    title = normalize_title(event_data.get("name"))
    start_date_raw = event_data.get("startDate")
    if not title or not start_date_raw:
        return None

    start_date = parse_event_datetime(start_date_raw)
    end_date = parse_event_datetime(event_data["endDate"]) if event_data.get("endDate") else None
    if not is_current_or_future(start_date, end_date):
        return None

    cost = get_lowest_offer_price(event_data.get("offers"))
    source_url = event_data.get("url") or url
    if description and source_url not in description:
        description = f"{description}\n\nAllEvents source: {source_url}"

    category = infer_category(title, description or "")
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
        "source": "allevents",
        "source_id": source_id_from_url(source_url),
        "source_url": source_url,
        "organizer": ", ".join(
            clean_text(org.get("name"))
            for org in event_data.get("organizer", [])
            if isinstance(org, dict) and org.get("name")
        ) if isinstance(event_data.get("organizer"), list) else None,
    }


def scrape_allevents(limit=None):
    listing_events = get_listing_events()
    if limit:
        listing_events = listing_events[:limit]

    events = []
    for index, listing_data in enumerate(listing_events, start=1):
        print(f"Processing {index}/{len(listing_events)}: {listing_data.get('url')}")
        event = get_event_details(listing_data)
        if event:
            events.append(event)
            print(f"  -> extracted: {event['title']}")
        else:
            print("  -> skipped past or incomplete event")
    return events


def save_events_to_db(events):
    print(f"  -> extracted {len(events)} AllEvents event(s)")
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
                Event.source == "allevents",
                Event.source_id == source_id,
            ).first()

            values = {
                "title": event_data["title"],
                "description": event_data.get("description"),
                "date": event_date,
                "cost": event_data.get("cost") if event_data.get("cost") is not None else 0.0,
                "location": event_data.get("location"),
                "category": event_data.get("category"),
                "special_tags": event_data.get("special_tags"),
                "vibe_tags": event_data.get("vibe_tags"),
                "source": "allevents",
                "source_id": source_id,
                "is_active": is_event_active(event_date),
                "source_url": event_data.get("source_url"),
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
        print("No AllEvents events passed extraction.")
        return

    print(f"\nPreviewing {len(events)} extracted AllEvents event(s); nothing has been saved.")
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
        "AllEvents LA Pop-Ups",
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
  <title>AllEvents LA Pop-Ups</title>
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
  <h1>AllEvents LA Pop-Ups</h1>
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
    parser = argparse.ArgumentParser(description="Scrape AllEvents LA pop-up events.")
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save extracted events to the database. By default, this only previews results.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit the number of listing events processed.",
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

    events = scrape_allevents(limit=args.limit)
    if args.output:
        export_events(events, args.output, args.format)
        print(f"\nWrote {len(events)} AllEvents events to {args.output}")
    elif args.save:
        total = save_events_to_db(events)
        print(f"\nDone. Total AllEvents events saved/updated: {total}")
    else:
        print_events_preview(events)
        print(f"\nDone. Total AllEvents events previewed: {len(events)}")
