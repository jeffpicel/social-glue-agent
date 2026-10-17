"""You.com search for real events, cached to disk so the demo never stalls on the network."""
import hashlib
import json
import os
from pathlib import Path

CACHE = Path("cache/events")

FALLBACK = [
    {"title": "Sunday farmers market + live jazz", "url": "", "snippet": "Free, outdoors, 10am-2pm"},
    {"title": "Thursday trivia night at a local brewery", "url": "", "snippet": "Teams up to 6, starts 7pm"},
    {"title": "Saturday board game cafe meetup", "url": "", "snippet": "$10 cover, all levels"},
]


def search_events(city: str, interests: str, when: str = "this month") -> list[dict]:
    query = f"events in {city} {when} for people into {interests}"
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / (hashlib.sha1(query.encode()).hexdigest()[:12] + ".json")
    if path.exists():
        return json.loads(path.read_text())
    results = FALLBACK
    key = os.getenv("YOU_API_KEY") or os.getenv("YDC_API_KEY")
    if key:
        try:
            import requests

            r = requests.get("https://api.ydc-index.io/search", params={"query": query}, headers={"X-API-Key": key}, timeout=10)
            r.raise_for_status()
            hits = r.json().get("hits", [])[:5]
            results = [{"title": h.get("title", ""), "url": h.get("url", ""), "snippet": (h.get("snippets") or [h.get("description", "")])[0]} for h in hits] or FALLBACK
        except Exception as e:  # noqa: BLE001 - demo must not crash on search
            print(f"[you.com] falling back to canned events: {e}")
            return FALLBACK
        else:
            path.write_text(json.dumps(results, indent=2))  # only cache real results
    return results
