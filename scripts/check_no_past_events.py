"""Smoke test: hit /agent/query and /for-you, verify no past events return.

Run while uvicorn is up on :8000. Anonymous calls only (no JWT) so /for-you
will 401 — that's fine; we mainly care about /agent/query. To test /for-you
authenticated, paste a valid Supabase JWT into JWT_OVERRIDE below.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

BASE_URL = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000")
JWT_OVERRIDE = os.environ.get("JWT", "")
LA = ZoneInfo("America/Los_Angeles")


def parse_start(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.astimezone(LA).replace(tzinfo=None) if dt.tzinfo else dt
    except Exception:
        return None


def run_agent_query(query: str) -> list[dict]:
    """Read the SSE stream and return the final results list."""
    with httpx.stream(
        "POST",
        f"{BASE_URL}/agent/query",
        json={"query": query, "chips": [], "happening_now": False},
        timeout=60,
    ) as r:
        r.raise_for_status()
        events: list[dict] = []
        buffer = ""
        for chunk in r.iter_text():
            buffer += chunk
            while "\n\n" in buffer:
                block, buffer = buffer.split("\n\n", 1)
                event_type, data = None, None
                for line in block.splitlines():
                    if line.startswith("event:"):
                        event_type = line[len("event:"):].strip()
                    elif line.startswith("data:"):
                        data = line[len("data:"):].strip()
                if event_type == "results" and data:
                    parsed = json.loads(data)
                    events = parsed.get("events", [])
        return events


def check(name: str, events: list[dict]) -> None:
    now = datetime.now(LA).replace(tzinfo=None)
    past = []
    for e in events:
        start = parse_start(e.get("start_time"))
        if start and start < now:
            past.append((e.get("title", "<no title>"), e.get("start_time")))
    status = "FAIL" if past else "PASS"
    print(f"[{status}] {name}: {len(events)} events, {len(past)} past")
    for title, start in past[:5]:
        print(f"    PAST -> {start}  {title!r}")


def main() -> None:
    print(f"Now (LA): {datetime.now(LA).isoformat()}")
    print(f"Base URL: {BASE_URL}\n")

    print("== /agent/query (default search) ==")
    for q in ["music", "food trucks", "art events this weekend"]:
        try:
            check(f"query={q!r}", run_agent_query(q))
        except Exception as exc:
            print(f"[ERROR] query={q!r}: {exc}")

    print("\n== /for-you ==")
    if not JWT_OVERRIDE:
        print("[SKIP] set JWT=<supabase-jwt> env var to test for-you (needs auth)")
        return
    try:
        r = httpx.get(
            f"{BASE_URL}/for-you",
            headers={"Authorization": f"Bearer {JWT_OVERRIDE}"},
            params={"limit": 20},
            timeout=60,
        )
        r.raise_for_status()
        check("for-you", r.json().get("events", []))
    except Exception as exc:
        print(f"[ERROR] for-you: {exc}")


if __name__ == "__main__":
    main()
