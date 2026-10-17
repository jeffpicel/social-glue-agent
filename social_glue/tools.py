"""Event search (Serper/Google first, then You.com), cached to disk so the demo never stalls on the network."""
import hashlib
import json
import os
from pathlib import Path

CACHE = Path("cache/events")

FALLBACK = [
    {"title": "Sunday farmers market + live jazz", "url": "", "snippet": "Free, outdoors, 10am-2pm"},
    {"title": "Thursday trivia night at a local brewery", "url": "", "snippet": "Teams up to 6, 7pm-9pm"},
    {"title": "Saturday board game cafe meetup", "url": "", "snippet": "$10 cover, all levels, 6:30pm-9:30pm"},
]


def _serper(query: str) -> list[dict]:
    """Google results via serper.dev."""
    import requests

    r = requests.post("https://google.serper.dev/search", json={"q": query, "num": 10},
                      headers={"X-API-KEY": os.environ["SERPER_API_KEY"]}, timeout=10)
    r.raise_for_status()
    organic = r.json().get("organic", [])[:5]
    return [{"title": h.get("title", ""), "url": h.get("link", ""), "snippet": " ".join(x for x in (h.get("date"), h.get("snippet")) if x)} for h in organic]


def search_events(city: str, interests: str, when: str = "this month") -> list[dict]:
    query = f"events in {city} {when} for people into {interests} (partiful OR lu.ma OR eventbrite) date time"
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / (hashlib.sha1(query.encode()).hexdigest()[:12] + ".json")
    if path.exists():
        return json.loads(path.read_text())
    results = FALLBACK
    if os.getenv("SERPER_API_KEY"):
        try:
            hits = _serper(query)
            if hits:
                path.write_text(json.dumps(hits, indent=2))
                return hits
        except Exception as e:  # noqa: BLE001 - fall through to You.com, then canned events
            print(f"[serper] search failed: {e}")
    key = os.getenv("YOU_API_KEY") or os.getenv("YDC_API_KEY")
    if key:
        try:
            import requests

            hits, err = [], None
            # Newer keys only work on ydc-index.io/v1 (results.web); older ones on api.ydc-index.io (hits).
            for url in ("https://ydc-index.io/v1/search", "https://api.ydc-index.io/search"):
                try:
                    r = requests.get(url, params={"query": query}, headers={"X-API-Key": key}, timeout=10)
                    r.raise_for_status()
                    body = r.json()
                    hits = (body.get("results") or {}).get("web") or body.get("hits") or []
                    hits = hits[:5]
                    break
                except Exception as e:  # noqa: BLE001
                    err = e
            if not hits and err:
                raise err
            results = [{"title": h.get("title", ""), "url": h.get("url", ""), "snippet": (h.get("snippets") or [h.get("description", "")])[0]} for h in hits] or FALLBACK
        except Exception as e:  # noqa: BLE001 - demo must not crash on search
            print(f"[you.com] falling back to canned events: {e}")
            return FALLBACK
        else:
            path.write_text(json.dumps(results, indent=2))  # only cache real results
    return results
