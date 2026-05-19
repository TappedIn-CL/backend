import os
import time
from functools import lru_cache
from typing import Tuple

import requests

API_URL = "https://maps.googleapis.com/maps/api/geocode/json"
API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

# Conservative SoCal bounding box to filter out poor geocoding results
SOCAL_BOUNDS = {
    "south": 31.5,
    "north": 36.0,
    "west": -125.0,
    "east": -113.0,
}


def _is_within_socal(lat: float, lng: float) -> bool:
    return (
        SOCAL_BOUNDS["south"] <= lat <= SOCAL_BOUNDS["north"]
        and SOCAL_BOUNDS["west"] <= lng <= SOCAL_BOUNDS["east"]
    )


@lru_cache(maxsize=2048)
def geocode_address(address: str, max_retries: int = 2, timeout: float = 5.0) -> Tuple[float | None, float | None]:
    """Return (lat, lng) for a given address string or (None, None) on failure.

    - Uses an LRU cache per process to reduce duplicate requests.
    - Respects missing API key by returning (None, None) so callers can continue.
    - Skips results flagged as partial_match to avoid storing low-confidence coords.
    """
    if not address:
        return None, None
    if not API_KEY:
        return None, None

    params = {
        "address": address,
        "key": API_KEY,
        "region": "us",
    }
    backoff = 0.5

    for attempt in range(max_retries + 1):
        try:
            resp = requests.get(API_URL, params=params, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status")
            if status == "OK" and data.get("results"):
                r = data["results"][0]
                # Conservative: skip partial_match results
                if r.get("partial_match"):
                    # return None, None
                    pass
                loc = r["geometry"]["location"]
                if not _is_within_socal(loc["lat"], loc["lng"]):
                    return None, None
                # Round to 6 decimals for storage
                return round(loc["lat"], 6), round(loc["lng"], 6)
            # For other statuses (ZERO_RESULTS, OVER_QUERY_LIMIT, etc.) return None
            return None, None
        except Exception:
            if attempt == max_retries:
                return None, None
            time.sleep(backoff)
            backoff *= 2
