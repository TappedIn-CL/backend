"""Backfill script to geocode existing events with missing coordinates.

Run from the backend folder with your virtualenv active. Requires `GOOGLE_MAPS_API_KEY` in `.env`.
"""
import os
from time import sleep

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from db.session import SessionLocal
from app.models.event import Event
from app.utils.geocoding import geocode_address


def run(batch_size: int = 50, pause_seconds: float = 0.5):
    db = SessionLocal()
    try:
        query = db.query(Event).filter(Event.location != None).filter(
            (Event.latitude == None) | (Event.longitude == None)
        )
        total = query.count()
        print(f"Found {total} events needing coordinates")

        processed = 0
        while True:
            # Always pull the next unresolved batch. Avoid offsets because the
            # result set shrinks as rows get updated.
            rows = query.limit(batch_size).all()
            if not rows:
                break
            previous_processed = processed
            for e in rows:
                lat, lng = geocode_address(e.location)
                if lat is not None and lng is not None:
                    e.latitude = lat
                    e.longitude = lng
                    processed += 1
            db.commit()
            print(f"Processed batch, total processed: {processed}")
            
            # If no progress was made in this batch, remaining rows are ungeocodable -> stop to avoid loop
            if processed == previous_processed:
                ungeocodable = len(rows)
                print(f"⚠ No progress in last batch. {ungeocodable} locations are ungeocodable, stopping.")
                break
            
            sleep(pause_seconds)

        print(f"Backfill complete. Total coordinates added/updated: {processed}")
    finally:
        db.close()


if __name__ == '__main__':
    run()
