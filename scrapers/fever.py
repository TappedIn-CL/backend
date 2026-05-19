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


BASE_URL = "https://feverup.com"
LA_EVENTS_URL = f"{BASE_URL}/en/los-angeles"

headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}


def clean_text(value):
    value = html.unescape(str(value or ""))
    return re.sub(r"\s+", " ", value).strip()


def get_soup(url):
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    # Fever's responses are UTF-8, but requests can infer ISO-8859-1.
    text = response.content.decode("utf-8", errors="replace")
    return BeautifulSoup(text, "html.parser")


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
        if isinstance(block, dict) and block.get("@type") == "Event" and block.get("startDate"):
            return block
    return {}


def normalize_title(title):
    return clean_text(title)


def source_id_from_url(url):
    path = urlparse(url).path.rstrip("/")
    event_id = path.rsplit("/", 1)[-1]
    return event_id if event_id else hashlib.md5(path.encode()).hexdigest()


def is_current_or_ongoing(start_date, end_date=None, today=None):
    comparison_date = end_date or start_date
    return comparison_date.date() >= (today or date_cls.today())


def get_event_links(index_url=LA_EVENTS_URL):
    soup = get_soup(index_url)

    links = []
    seen = set()
    for link_el in soup.select('a.fv-plan-preview-card__link[href*="/m/"], a[href^="/m/"]'):
        url = urljoin(BASE_URL, link_el["href"]).split("?")[0]
        source_id = source_id_from_url(url)
        if source_id in seen:
            continue

        title_el = link_el.select_one('[data-testid="plan-preview-card-name"], .fv-plan-preview-card__name')
        image_el = link_el.select_one("img[alt]")
        title = clean_text(title_el.get_text(" ", strip=True) if title_el else image_el.get("alt") if image_el else "")
        links.append({
            "url": url,
            "title": title,
            "source_id": source_id,
            "carousel": link_el.get("data-plan-card-carousel-name"),
        })
        seen.add(source_id)

    return links


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
        ])
    elif address:
        parts.append(address)

    return clean_text(", ".join(part for part in parts if part)) or None


def extract_description(soup, event_data):
    description_el = soup.select_one(".plan-description")
    if description_el:
        text = description_el.get_text("\n", strip=True)
        lines = []
        for line in (clean_text(part) for part in text.splitlines()):
            if line and line not in {"Event Details", "Description", "Getting there"}:
                lines.append(line)
        if lines:
            return "\n".join(lines)[:1800]

    description = clean_text(event_data.get("description"))
    description = re.sub(r"@import url\([^)]+\);", " ", description)
    description = re.sub(r"\.[^{]+\{[^}]+\}", " ", description)
    return clean_text(description)[:1800] or None


def get_lowest_offer_price(offers):
    if isinstance(offers, dict):
        offers = [offers]
    if not isinstance(offers, list):
        return 0.0

    prices = []
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        value = offer.get("price") or offer.get("lowPrice")
        if value in (None, ""):
            continue
        try:
            prices.append(float(value))
        except (TypeError, ValueError):
            pass
    return min(prices) if prices else 0.0


def normalize_category(title, description):
    text = f"{title} {description}".casefold()
    if re.search(r"\b(candlelight|concert|music|orchestra|jazz|tribute|live music|ballet|opera)\b", text):
        return "Music"
    if re.search(r"\b(food|drink|cocktail|dinner|brunch|restaurant|tasting|wine|beer)\b", text):
        return "Food & Drink"
    if re.search(r"\b(comedy|comedian|stand[- ]?up)\b", text):
        return "Comedy"
    if re.search(r"\b(immersive|exhibit|exhibition|museum|art|paint|craft|cinema|movie|film|theatre|theater|burlesque|show)\b", text):
        return "Arts"
    if re.search(r"\b(yoga|wellness|fitness|meditation|workout|pilates)\b", text):
        return "Wellness"
    if re.search(r"\b(party|club|nightlife|dj|dance)\b", text):
        return "Nightlife"
    if re.search(r"\b(sports|game|adventure)\b", text):
        return "Sports"
    if re.search(r"\b(family|kids|children|all ages)\b", text):
        return "Family"
    if re.search(r"\b(fashion|beauty|style)\b", text):
        return "Fashion"
    return "Other"


def infer_special_tags(title, description, cost):
    text = f"{title} {description}".casefold()
    tags = []
    if cost == 0.0 and re.search(r"\b(free admission|free event|free ticket|free tickets)\b", text):
        tags.append("Free perks")
    if "21+" in text or "21 and over" in text:
        tags.append("21+")
    if any(word in text for word in ("family-friendly", "kid-friendly", "kids", "children", "all ages")):
        tags.append("Family-friendly")
    if any(word in text for word in ("outdoor", "open-air", "rooftop", "garden", "stadium")):
        tags.append("Outdoor")
    if any(word in text for word in ("limited", "selling fast", "sold out", "waitlist")):
        tags.append("Limited spots")
    if any(word in text for word in ("pop-up", "popup", "pop up")):
        tags.append("Pop-up")

    valid_tags = [tag for tag in tags if tag in ALLOWED_SPECIAL_TAGS]
    return ",".join(dict.fromkeys(valid_tags)) if valid_tags else None


def infer_vibe_tags(title, description, category):
    text = f"{title} {description}".casefold()
    tags = []
    if category in {"Arts", "Fashion"} or any(word in text for word in ("immersive", "art", "craft", "film", "theater")):
        tags.append("Creative")
    if category in {"Music", "Nightlife", "Sports"} or any(word in text for word in ("party", "dance", "festival", "adventure")):
        tags.append("Energetic")
    if category in {"Food & Drink", "Networking"}:
        tags.append("Social")
    if any(word in text for word in ("candlelight", "intimate", "romantic")):
        tags.append("Intimate")
    if any(word in text for word in ("family-friendly", "kid-friendly", "kids", "children", "all ages")):
        tags.append("Chill")
    if any(word in text for word in ("museum", "exhibition", "learn", "workshop", "educational")):
        tags.append("Educational")

    valid_tags = [tag for tag in tags if tag in VIBE_TAGS]
    return ",".join(dict.fromkeys(valid_tags)) if valid_tags else None


def get_event_details(listing_data):
    url = listing_data.get("url")
    if not url:
        return None

    soup = get_soup(url)
    event_data = get_event_json_ld(soup)
    if not event_data:
        return None

    title = normalize_title(event_data.get("name") or listing_data.get("title"))
    start_date_raw = event_data.get("startDate")
    if not title or not start_date_raw:
        return None

    start_date = parse_event_datetime(start_date_raw)
    end_date = parse_event_datetime(event_data["endDate"]) if event_data.get("endDate") else None
    if not is_current_or_ongoing(start_date, end_date):
        return None

    source_url = event_data.get("url") or url
    description = extract_description(soup, event_data)
    if description and source_url not in description:
        description = f"{description}\n\nFever source: {source_url}"

    cost = get_lowest_offer_price(event_data.get("offers"))
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
        "vibe_tags": infer_vibe_tags(title, description or "", category),
        "source": "fever",
        "source_id": listing_data.get("source_id") or source_id_from_url(source_url),
        "source_url": source_url,
        "carousel": listing_data.get("carousel"),
    }


def scrape_fever(limit=None):
    links = get_event_links()
    if limit:
        links = links[:limit]

    events = []
    for index, link in enumerate(links, start=1):
        print(f"Processing {index}/{len(links)}: {link['url']}")
        try:
            event = get_event_details(link)
            if event:
                events.append(event)
                print(f"  -> extracted: {event['title']}")
            else:
                print("  -> skipped past or incomplete event")
        except Exception as ex:
            print(f"  -> Error: {ex}")
    return events


def save_events_to_db(events):
    print(f"  -> extracted {len(events)} Fever event(s)")
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
                Event.source == "fever",
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
                "source": "fever",
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
        print("No Fever events passed extraction.")
        return

    print(f"\nPreviewing {len(events)} extracted Fever event(s); nothing has been saved.")
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
        f"Fever carousel: {event.get('carousel') or ''}",
        f"URL: {event.get('source_url') or ''}",
    ]
    if event.get("description"):
        lines.extend(["", event["description"]])
    return "\n".join(lines)


def export_events_to_txt(events, output_path):
    content = [
        "Fever LA Events",
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
            <dt>Fever carousel</dt><dd>{html.escape(event.get("carousel") or "")}</dd>
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
  <title>Fever LA Events</title>
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
  <h1>Fever LA Events</h1>
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
    parser = argparse.ArgumentParser(description="Scrape Fever LA events.")
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
        "--output",
        help="Write scraped events to an HTML, TXT, or JSON file without saving to the database.",
    )
    parser.add_argument(
        "--format",
        choices=("html", "txt", "json"),
        help="Output format. Defaults to the --output file extension.",
    )
    args = parser.parse_args()

    events = scrape_fever(limit=args.limit)
    if args.output:
        export_events(events, args.output, args.format)
        print(f"\nWrote {len(events)} Fever events to {args.output}")
    elif args.save:
        total = save_events_to_db(events)
        print(f"\nDone. Total Fever events saved/updated: {total}")
    else:
        print_events_preview(events)
        print(f"\nDone. Total Fever events previewed: {len(events)}")
