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
from db.session import SessionLocal
from scrapers.date_utils import parse_event_datetime


BASE_URL = "https://dolosangeles.com"
EVENTS_URL = f"{BASE_URL}/"

headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}

CATEGORY_MAP = {
    "art-fashion": "Arts",
    "comedic-events": "Comedy",
    "comedy": "Comedy",
    "concert-music-festival": "Music",
    "cultural-community": "Networking",
    "dj-parties": "Nightlife",
    "exhibits-educational": "Arts",
    "film-television": "Arts",
    "films-tv-drive-ins": "Arts",
    "food-drink": "Food & Drink",
    "lgbtq": "Nightlife",
    "music": "Music",
    "performing-arts": "Arts",
    "sports-health-fitness": "Sports",
}


def clean_text(value):
    value = html.unescape(str(value or ""))
    return re.sub(r"\s+", " ", value).strip()


def get_meta_content(scope, itemprop):
    tag = scope.select_one(f'[itemprop="{itemprop}"]')
    if not tag:
        return None
    return tag.get("content") or tag.get("datetime") or tag.get("title") or clean_text(tag.get_text(" ", strip=True))


def normalize_title(title):
    return clean_text(title)


def source_id_from_url(url):
    path = urlparse(url).path.rstrip("/")
    event_slug = path.rsplit("/", 1)[-1]
    return event_slug if event_slug else hashlib.md5(path.encode()).hexdigest()


def is_current_or_future(start_date, today=None):
    return start_date.date() >= (today or date_cls.today())


def category_slug_from_card(card):
    for class_name in card.get("class", []):
        if class_name.startswith("ds-event-category-"):
            return class_name.replace("ds-event-category-", "", 1)
    return None


def normalize_category(category_slug, title, description):
    mapped = CATEGORY_MAP.get(category_slug or "")
    if mapped in ALLOWED_EVENT_CATEGORIES:
        if category_slug == "sports-health-fitness":
            text = f"{title} {description}".casefold()
            if re.search(r"\b(yoga|pilates|fitness|workout|wellness|meditation|health)\b", text):
                return "Wellness"
        return mapped

    text = f"{title} {description}".casefold()
    if re.search(r"\b(food|drink|restaurant|dinner|brunch|beer|wine|cocktail|tasting)\b", text):
        return "Food & Drink"
    if re.search(r"\b(comedy|comedian|stand[- ]?up|open mic)\b", text):
        return "Comedy"
    if re.search(r"\b(concert|music|band|singer|tour|album|dj)\b", text):
        return "Music"
    if re.search(r"\b(party|club|dance|nightlife)\b", text):
        return "Nightlife"
    if re.search(r"\b(film|movie|screening|art|gallery|museum|theatre|theater|performance)\b", text):
        return "Arts"
    if re.search(r"\b(yoga|fitness|wellness|meditation|workout)\b", text):
        return "Wellness"
    if re.search(r"\b(game|sports|basketball|baseball|soccer|hockey|football)\b", text):
        return "Sports"
    if re.search(r"\b(family|kids|children)\b", text):
        return "Family"
    if re.search(r"\b(fashion|beauty|style)\b", text):
        return "Fashion"
    if re.search(r"\b(networking|community|meetup|panel|talk)\b", text):
        return "Networking"
    return "Other"


def normalize_location(scope):
    location = scope.select_one('[itemprop="location"]')
    if not location:
        return None

    name_el = location.select_one('[itemprop="name"]')
    address = location.select_one('[itemprop="address"]')
    parts = [clean_text(name_el.get_text(" ", strip=True)) if name_el else None]
    if address:
        parts.extend([
            get_meta_content(address, "streetAddress"),
            get_meta_content(address, "addressLocality"),
            get_meta_content(address, "addressRegion"),
            get_meta_content(address, "postalCode"),
        ])

    return clean_text(", ".join(part for part in parts if part)) or None


def extract_cost(scope, description=""):
    price = get_meta_content(scope, "price")
    text = f"{price or ''} {description or ''}"
    if re.search(r"\bfree\b|no cost|complimentary", text, re.I):
        return 0.0

    price_match = re.search(r"\$(\d+(?:\.\d{1,2})?)", text)
    if price_match:
        return float(price_match.group(1))

    try:
        return float(price) if price not in (None, "") else 0.0
    except (TypeError, ValueError):
        return 0.0


def infer_special_tags(title, description, cost):
    text = f"{title} {description}".casefold()
    tags = []
    has_free_signal = re.search(r"\b(free admission|free event|free show|free ticket|free tickets|rsvp for free)\b", text)
    if cost == 0.0 and has_free_signal:
        tags.append("Free perks")
    if "21+" in text or "21 and over" in text:
        tags.append("21+")
    if any(word in text for word in ("family-friendly", "kid-friendly", "kids", "children")):
        tags.append("Family-friendly")
    if any(word in text for word in ("outdoor", "park", "rooftop", "garden", "beach")):
        tags.append("Outdoor")
    if any(word in text for word in ("limited", "capacity", "sold out")):
        tags.append("Limited spots")
    if any(word in text for word in ("pop-up", "popup", "pop up")):
        tags.append("Pop-up")

    valid_tags = [tag for tag in tags if tag in ALLOWED_SPECIAL_TAGS]
    return ",".join(dict.fromkeys(valid_tags)) if valid_tags else None


def infer_vibe_tags(title, description, category):
    text = f"{title} {description}".casefold()
    tags = []
    if category in {"Arts", "Fashion"} or any(word in text for word in ("art", "craft", "film", "gallery", "creative")):
        tags.append("Creative")
    if category in {"Music", "Nightlife", "Sports"} or any(word in text for word in ("party", "dance", "festival", "rave")):
        tags.append("Energetic")
    if category in {"Networking", "Food & Drink"} or any(word in text for word in ("community", "meetup", "social")):
        tags.append("Social")
    if any(word in text for word in ("intimate", "acoustic", "listening room")):
        tags.append("Intimate")
    if any(word in text for word in ("family-friendly", "kid-friendly", "kids", "children")):
        tags.append("Chill")
    if any(word in text for word in ("educational", "workshop", "panel", "talk")):
        tags.append("Educational")

    valid_tags = [tag for tag in tags if tag in VIBE_TAGS]
    return ",".join(dict.fromkeys(valid_tags)) if valid_tags else None


def listing_event_from_card(card):
    link_el = card.select_one(".ds-listing-event-title[href], a[itemprop='url'][href]")
    title_el = card.select_one('[itemprop="name"], .ds-listing-event-title-text')
    start_date_raw = get_meta_content(card, "startDate")
    if not link_el or not title_el or not start_date_raw:
        return None

    url = urljoin(BASE_URL, link_el["href"]).split("?")[0]
    title = normalize_title(title_el.get_text(" ", strip=True))
    try:
        start_date = parse_event_datetime(start_date_raw)
    except ValueError:
        return None

    if not title or not is_current_or_future(start_date):
        return None

    return {
        "title": title,
        "date": start_date.isoformat(),
        "start_date": start_date.isoformat(),
        "end_date": None,
        "location": normalize_location(card),
        "source": "dolosangeles",
        "source_id": source_id_from_url(url),
        "source_url": url,
        "category_slug": category_slug_from_card(card),
    }


def get_listing_events(index_url=EVENTS_URL, max_pages=3):
    events = []
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

        for card in soup.select(".ds-listing.event-card[itemtype='http://schema.org/Event']"):
            event = listing_event_from_card(card)
            if not event or event["source_url"] in seen:
                continue
            events.append(event)
            seen.add(event["source_url"])

        next_link = soup.select_one("a.ds-next-page[href]")
        next_url = urljoin(next_url, next_link["href"]) if next_link else None

    return events


def extract_description(soup):
    description_el = soup.select_one(".ds-event-description-inner, .ds-event-description")
    if not description_el:
        return None

    lines = []
    for line in (clean_text(part) for part in description_el.get_text("\n", strip=True).splitlines()):
        if line:
            lines.append(line)

    return "\n".join(lines)[:1800] or None


def get_event_details(listing_data):
    url = listing_data.get("source_url")
    if not url:
        return None

    event = dict(listing_data)
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
    except Exception as ex:
        print(f"  -> detail fetch failed, using listing data: {ex}")
        soup = None

    detail_scope = soup.select_one('[itemtype="http://schema.org/Event"]') if soup else None
    if detail_scope:
        title_el = detail_scope.select_one('[itemprop="name"]')
        start_date_raw = get_meta_content(detail_scope, "startDate")
        if title_el:
            event["title"] = normalize_title(title_el.get_text(" ", strip=True))
        if start_date_raw:
            start_date = parse_event_datetime(start_date_raw)
            if not is_current_or_future(start_date):
                return None
            event["date"] = start_date.isoformat()
            event["start_date"] = start_date.isoformat()
        event["location"] = normalize_location(detail_scope) or event.get("location")

    description = extract_description(soup) if soup else None
    if description and url not in description:
        description = f"{description}\n\nDoLA source: {url}"

    cost = extract_cost(detail_scope or BeautifulSoup("", "html.parser"), description or "")
    category = normalize_category(event.get("category_slug"), event["title"], description or "")
    event.update({
        "description": description,
        "cost": cost,
        "category": category,
        "special_tags": infer_special_tags(event["title"], description or "", cost),
        "vibe_tags": infer_vibe_tags(event["title"], description or "", category),
    })
    return event


def scrape_dolosangeles(limit=None, max_pages=3):
    listing_events = get_listing_events(max_pages=max_pages)
    if limit:
        listing_events = listing_events[:limit]

    events = []
    for index, listing_data in enumerate(listing_events, start=1):
        print(f"Processing {index}/{len(listing_events)}: {listing_data['source_url']}")
        try:
            event = get_event_details(listing_data)
            if event:
                events.append(event)
                print(f"  -> extracted: {event['title']}")
            else:
                print("  -> skipped past or incomplete event")
        except Exception as ex:
            print(f"  -> Error: {ex}")
    return events


def save_events_to_db(events):
    print(f"  -> extracted {len(events)} DoLA event(s)")
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
                Event.source == "dolosangeles",
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
                "source": "dolosangeles",
                "source_id": source_id,
                "source_url": event_data.get("source_url"),
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
        print("No DoLA events passed extraction.")
        return

    print(f"\nPreviewing {len(events)} extracted DoLA event(s); nothing has been saved.")
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
        f"URL: {event.get('source_url') or ''}",
    ]
    if event.get("description"):
        lines.extend(["", event["description"]])
    return "\n".join(lines)


def export_events_to_txt(events, output_path):
    content = [
        "DoLA Events",
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
  <title>DoLA Events</title>
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
  <h1>DoLA Events</h1>
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
    parser = argparse.ArgumentParser(description="Scrape DoLA events.")
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
        "--max-pages",
        type=int,
        default=3,
        help="Maximum number of DoLA listing pages to crawl.",
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

    events = scrape_dolosangeles(limit=args.limit, max_pages=args.max_pages)
    if args.output:
        export_events(events, args.output, args.format)
        print(f"\nWrote {len(events)} DoLA events to {args.output}")
    elif args.save:
        total = save_events_to_db(events)
        print(f"\nDone. Total DoLA events saved/updated: {total}")
    else:
        print_events_preview(events)
        print(f"\nDone. Total DoLA events previewed: {len(events)}")
