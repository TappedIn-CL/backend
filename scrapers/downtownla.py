import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import argparse
import hashlib
import html
import json
import re
from datetime import date as date_cls
from datetime import datetime, time, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from app.models.event import ALLOWED_EVENT_CATEGORIES, ALLOWED_SPECIAL_TAGS, VIBE_TAGS, Event
from app.utils.event_utils import enforce_coordinates_for_ingestion, is_event_active
from db.session import SessionLocal
from scrapers.date_utils import parse_event_datetime


BASE_URL = "https://downtownla.com"
CALENDAR_URL = f"{BASE_URL}/calendar"
RESULTS_URL = f"{BASE_URL}/_templates/_bbq_results.php"

headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "X-Requested-With": "XMLHttpRequest",
}


def clean_text(value):
    value = html.unescape(str(value or ""))
    return re.sub(r"\s+", " ", value).strip()


def parse_hash_date(value):
    value = (value or "").strip().lstrip("#")
    match = re.match(r"^(\d{1,2})-(\d{1,2})-(\d{2}|\d{4})$", value)
    if not match:
        return date_cls.today()

    month, day, year = (int(part) for part in match.groups())
    if year < 100:
        year += 2000
    return date_cls(year, month, day)


def date_to_hash(value):
    return f"{value.month}-{value.day}-{str(value.year)[-2:]}"


def clean_source_url(url):
    return urljoin(BASE_URL, url).split("?")[0]


def source_id_from_url(url):
    path = urlparse(url).path.rstrip("/")
    slug = path.rsplit("/", 1)[-1]
    return slug if slug else hashlib.md5(path.encode()).hexdigest()


def is_current_or_ongoing(start_date, end_date=None, today=None):
    comparison_date = end_date or start_date
    return comparison_date.date() >= (today or date_cls.today())


def event_date_for_storage(start_date, end_date=None, today=None):
    today = today or date_cls.today()
    if start_date.date() >= today:
        return start_date
    if end_date and end_date.date() >= today:
        return datetime.combine(today, time.min)
    return start_date


def parse_time_range(time_text):
    time_text = clean_text(time_text).lower()
    if not time_text:
        return None

    first = re.split(r"\s*[-–]\s*", time_text, maxsplit=1)[0]
    first = first.replace(".", "")
    match = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)", first)
    if not match:
        return None

    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    meridiem = match.group(3)
    if meridiem == "pm" and hour != 12:
        hour += 12
    if meridiem == "am" and hour == 12:
        hour = 0
    return hour, minute


def parse_detail_date(date_text, time_text=None):
    date_text = clean_text(date_text)
    if not date_text:
        return None, None

    # Examples:
    # Monday, May 25, 2026
    # Tue, May 19, 2026 - Fri, May 22, 2026
    date_matches = re.findall(r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+([A-Z][a-z]{2,8}\s+\d{1,2},\s+\d{4})", date_text)
    if not date_matches:
        date_matches = re.findall(r"([A-Z][a-z]{2,8}\s+\d{1,2},\s+\d{4})", date_text)

    if not date_matches:
        return None, None

    start_date = datetime.strptime(date_matches[0], "%b %d, %Y") if len(date_matches[0].split()[0]) == 3 else datetime.strptime(date_matches[0], "%B %d, %Y")
    end_date = None
    if len(date_matches) > 1:
        end_date = datetime.strptime(date_matches[-1], "%b %d, %Y") if len(date_matches[-1].split()[0]) == 3 else datetime.strptime(date_matches[-1], "%B %d, %Y")

    parsed_time = parse_time_range(time_text)
    if parsed_time:
        start_date = start_date.replace(hour=parsed_time[0], minute=parsed_time[1])
    return start_date, end_date


def parse_listing_secondary(text):
    text = clean_text(text)
    if not text:
        return None, None

    through_match = re.match(r"through\s+(\d{1,2}/\d{1,2}/\d{4})(?:\s+(.+))?$", text, re.I)
    if through_match:
        return f"through {through_match.group(1)}", clean_text(through_match.group(2))

    time_match = re.match(r"(.+?(?:am|pm|close))(?:\s+(.+))?$", text, re.I)
    if time_match:
        return clean_text(time_match.group(1)), clean_text(time_match.group(2))

    return None, text


def get_listing_events(start_date=None, days=7):
    start_date = start_date or date_cls.today()
    events_by_url = {}

    for offset in range(days):
        day = start_date + timedelta(days=offset)
        response = requests.get(
            RESULTS_URL,
            params={"bbqparam": date_to_hash(day)},
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        for row in soup.select(".bbq-row"):
            is_ongoing = row.select_one(".bbqdate-ongoing") is not None
            for link_el in row.select('.bbq-row-list a[href^="/do/"]'):
                url = clean_source_url(link_el["href"])
                title_el = link_el.select_one(".lnk-primary")
                secondary_el = link_el.select_one(".lnk-secondary")
                title = clean_text(title_el.get_text(" ", strip=True) if title_el else link_el.get_text(" ", strip=True))
                secondary = clean_text(secondary_el.get_text(" ", strip=True) if secondary_el else "")
                time_text, location_hint = parse_listing_secondary(secondary)

                if url not in events_by_url:
                    events_by_url[url] = {
                        "title": title,
                        "source_url": url,
                        "source_id": source_id_from_url(url),
                        "listing_date": day.isoformat(),
                        "time_text": time_text,
                        "location_hint": location_hint,
                        "is_ongoing": is_ongoing,
                    }

    return list(events_by_url.values())


def normalize_location(soup, fallback=None):
    venue = clean_text(soup.select_one(".map-detail-content-pname").get_text(" ", strip=True)) if soup.select_one(".map-detail-content-pname") else None
    address = clean_text(soup.select_one(".map-detail-content-paddress").get_text(", ", strip=True)) if soup.select_one(".map-detail-content-paddress") else None
    return clean_text(", ".join(part for part in (venue, address) if part)) or fallback


def extract_description(soup):
    content = soup.select_one(".max900 > .row")
    if not content:
        return None

    lines = []
    for paragraph in content.select("p"):
        text = clean_text(paragraph.get_text(" ", strip=True))
        if not text or text.casefold() == "visit website":
            continue
        lines.append(text)
    return "\n".join(lines)[:1800] or None


def extract_cost(description):
    text = description or ""
    if re.search(r"\b(free admission|free event|free ticket|free tickets|no cost)\b", text, re.I):
        return 0.0
    prices = []
    for match in re.finditer(r"\$(\d+(?:\.\d{1,2})?)", text):
        try:
            prices.append(float(match.group(1)))
        except ValueError:
            pass
    return min(prices) if prices else 0.0


def normalize_category(category_text, title, description):
    text = f"{category_text} {title} {description}".casefold()
    if any(word in text for word in ("concert", "music", "opera")):
        return "Music"
    if any(word in text for word in ("brunch", "food", "drink", "restaurant", "cocktail", "dining", "martini")):
        return "Food & Drink"
    if "comedy" in text:
        return "Comedy"
    if any(word in text for word in ("film", "theater", "theatre", "performance", "museum", "art", "exhibit", "dance")):
        return "Arts"
    if any(word in text for word in ("training", "running", "fitness", "wellness", "workshop")):
        return "Wellness"
    if "sports" in text:
        return "Sports"
    if "family friendly" in text:
        return "Family"
    if any(word in text for word in ("shopping", "fashion")):
        return "Fashion"
    if any(word in text for word in ("conference", "lecture", "debate", "benefit", "community")):
        return "Networking"
    return "Other"


def infer_special_tags(category_text, title, description, cost):
    text = f"{category_text} {title} {description}".casefold()
    tags = []
    if cost == 0.0 and re.search(r"\bfree\b|complimentary", text):
        tags.append("Free perks")
    if "21+" in text or "21 and over" in text:
        tags.append("21+")
    if "family friendly" in text or any(word in text for word in ("kids", "children")):
        tags.append("Family-friendly")
    if "outdoor" in text:
        tags.append("Outdoor")
    if any(word in text for word in ("limited", "reservation", "rsvp")):
        tags.append("Limited spots")
    if any(word in text for word in ("pop-up", "popup", "pop up")):
        tags.append("Pop-up")

    valid_tags = [tag for tag in tags if tag in ALLOWED_SPECIAL_TAGS]
    return ",".join(dict.fromkeys(valid_tags)) if valid_tags else None


def infer_vibe_tags(title, description, category):
    text = f"{title} {description}".casefold()
    tags = []
    if category in {"Arts", "Fashion"}:
        tags.append("Creative")
    if category in {"Music", "Sports", "Nightlife"} or any(word in text for word in ("festival", "running")):
        tags.append("Energetic")
    if category in {"Food & Drink", "Networking"}:
        tags.append("Social")
    if any(word in text for word in ("family", "kids", "children")):
        tags.append("Chill")
    if any(word in text for word in ("workshop", "lecture", "museum", "training")):
        tags.append("Educational")

    valid_tags = [tag for tag in tags if tag in VIBE_TAGS]
    return ",".join(dict.fromkeys(valid_tags)) if valid_tags else None


def get_detail_dates(soup, listing_data):
    dates = []
    for item in soup.select(".datelist li"):
        date_el = item.select_one(".dldate")
        if not date_el:
            continue
        time_el = item.select_one(".dltime")
        start_date, end_date = parse_detail_date(
            date_el.get_text(" ", strip=True),
            time_el.get_text(" ", strip=True) if time_el else listing_data.get("time_text"),
        )
        if start_date:
            dates.append((start_date, end_date))

    if dates:
        current_dates = [date_pair for date_pair in dates if is_current_or_ongoing(date_pair[0], date_pair[1])]
        return current_dates[0] if current_dates else dates[0]

    listing_date = listing_data.get("listing_date")
    if listing_date:
        start_date = datetime.fromisoformat(listing_date)
        parsed_time = parse_time_range(listing_data.get("time_text"))
        if parsed_time:
            start_date = start_date.replace(hour=parsed_time[0], minute=parsed_time[1])
        return start_date, None
    return None, None


def get_event_details(listing_data):
    response = requests.get(listing_data["source_url"], headers=headers, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    title_el = soup.select_one(".evdetail-h1, h1")
    title = clean_text(title_el.get_text(" ", strip=True)) if title_el else listing_data.get("title")
    if not title:
        return None

    start_date, end_date = get_detail_dates(soup, listing_data)
    if not start_date or not is_current_or_ongoing(start_date, end_date):
        return None

    category_text = clean_text(soup.select_one(".evdetail-tag").get_text(" ", strip=True)) if soup.select_one(".evdetail-tag") else ""
    description = extract_description(soup)
    if description and listing_data["source_url"] not in description:
        description = f"{description}\n\nDowntown LA source: {listing_data['source_url']}"

    cost = extract_cost(description or "")
    category = normalize_category(category_text, title, description or "")
    if category not in ALLOWED_EVENT_CATEGORIES:
        category = "Other"

    event_date = event_date_for_storage(start_date, end_date)

    return {
        "title": title,
        "description": description,
        "date": event_date.isoformat(),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat() if end_date else None,
        "cost": cost,
        "location": normalize_location(soup, listing_data.get("location_hint")),
        "category": category,
        "special_tags": infer_special_tags(category_text, title, description or "", cost),
        "vibe_tags": infer_vibe_tags(title, description or "", category),
        "source": "downtownla",
        "source_id": listing_data["source_id"],
        "source_url": listing_data["source_url"],
        "downtownla_categories": category_text,
    }


def scrape_downtownla(start_hash="5-18-26", days=7, limit=None):
    listing_events = get_listing_events(parse_hash_date(start_hash), days=days)
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
    print(f"  -> extracted {len(events)} Downtown LA event(s)")
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
                Event.source == "downtownla",
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
                "source": "downtownla",
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
        print("No Downtown LA events passed extraction.")
        return

    print(f"\nPreviewing {len(events)} extracted Downtown LA event(s); nothing has been saved.")
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
        f"Downtown LA categories: {event.get('downtownla_categories') or ''}",
        f"URL: {event.get('source_url') or ''}",
    ]
    if event.get("description"):
        lines.extend(["", event["description"]])
    return "\n".join(lines)


def export_events_to_txt(events, output_path):
    content = [
        "Downtown LA Events",
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
            <dt>Downtown LA categories</dt><dd>{html.escape(event.get("downtownla_categories") or "")}</dd>
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
  <title>Downtown LA Events</title>
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
  <h1>Downtown LA Events</h1>
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
    parser = argparse.ArgumentParser(description="Scrape Downtown LA calendar events.")
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save extracted events to the database. By default, this only previews results.",
    )
    parser.add_argument(
        "--start",
        default="5-18-26",
        help="Calendar start hash/date, e.g. 5-18-26. Defaults to the provided Downtown LA link date.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of calendar days to crawl from --start.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit the number of events processed.",
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

    events = scrape_downtownla(start_hash=args.start, days=args.days, limit=args.limit)
    if args.output:
        export_events(events, args.output, args.format)
        print(f"\nWrote {len(events)} Downtown LA events to {args.output}")
    elif args.save:
        total = save_events_to_db(events)
        print(f"\nDone. Total Downtown LA events saved/updated: {total}")
    else:
        print_events_preview(events)
        print(f"\nDone. Total Downtown LA events previewed: {len(events)}")
