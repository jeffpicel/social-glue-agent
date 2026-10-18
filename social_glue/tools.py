"""Event search (Serper/Google first, then You.com), cached to disk so the demo never stalls on the network."""
import hashlib
import json
import os
import re
from difflib import SequenceMatcher
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

CACHE = Path("cache/events")

FALLBACK = [
    {"title": "Sunday farmers market + live jazz", "url": "", "snippet": "Free, outdoors, 10am-2pm"},
    {"title": "Thursday trivia night at a local brewery", "url": "", "snippet": "Teams up to 6, 7pm-9pm"},
    {"title": "Saturday board game cafe meetup", "url": "", "snippet": "$10 cover, all levels, 6:30pm-9:30pm"},
]


LISTING = re.compile(r"/explore|/discover|/d/|/calendar|/search|/events/?$|things to do|events in|best events|app store|events calendar|/e/to/", re.I)


MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
EVENT_DATE = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.? (\d{1,2})(?:st|nd|rd|th)?(?:,? (20\d\d))?", re.I)


def _is_past(text: str, today: date) -> bool:
    """True if the first date the listing names is before today (no year means this year)."""
    m = EVENT_DATE.search(text)
    if not m:
        return False
    try:
        d = date(int(m.group(3) or today.year), MONTHS.index(m.group(1).lower()) + 1, int(m.group(2)))
    except ValueError:
        return False
    return d < today


def _serper(query: str) -> list[dict]:
    """Google results via serper.dev, single event pages only (listing pages make the group do the work)."""
    import requests

    today = date.today()
    q = query.split(" (")[0] + (
        " (site:lu.ma OR site:partiful.com/e OR site:eventbrite.com/e OR "
        "site:events.cerebralvalley.ai/e OR site:cerebralvalley.ai/e OR site:sf.funcheap.com OR site:todaytix.com OR "
        "site:ticketmaster.com/event OR site:stubhub.com OR site:vividseats.com)"
    )
    r = requests.post("https://google.serper.dev/search", json={"q": q, "num": 20},
                      headers={"X-API-KEY": os.environ["SERPER_API_KEY"]}, timeout=10)
    r.raise_for_status()
    organic = [h for h in r.json().get("organic", []) if not LISTING.search(h.get("link", "") + " " + h.get("title", ""))
               and not _is_past(" ".join(h.get(k) or "" for k in ("date", "title", "snippet")), today)
               and urlparse(h.get("link", "")).path.strip("/")][:5]
    return [{"title": h.get("title", ""), "url": h.get("link", ""), "snippet": " ".join(x for x in (h.get("date"), h.get("snippet")) if x)} for h in organic]


def search_events(city: str, interests: str, when: str = "this month") -> list[dict]:
    query = (
        f"events in {city} {when} for people into {interests} "
        "(partiful OR lu.ma OR eventbrite OR cerebral valley OR funcheap OR todaytix OR ticketmaster OR stubhub OR vivid seats) date time"
    )
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / (hashlib.sha1(("v6" + query).encode()).hexdigest()[:12] + ".json")
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


def search_yelp_places(city: str, term: str, limit: int = 5) -> list[dict]:
    """Search Yelp Places for concrete local businesses; returns [] when not configured."""
    key = os.getenv("YELP_API_KEY")
    if not key:
        return []

    import requests

    response = requests.get(
        "https://api.yelp.com/v3/businesses/search",
        params={"location": city, "term": term[:300], "limit": min(max(limit, 1), 50), "sort_by": "best_match"},
        headers={"Authorization": f"Bearer {key}", "accept": "application/json"},
        timeout=12,
    )
    response.raise_for_status()
    places = []
    for business in response.json().get("businesses", []):
        if business.get("is_closed") or not business.get("url"):
            continue
        categories = ", ".join(c.get("title", "") for c in business.get("categories", []) if c.get("title"))
        location = business.get("location") or {}
        address = ", ".join(part for part in (
            location.get("address1"), location.get("city"), location.get("state")
        ) if part)
        details = []
        if business.get("rating") is not None:
            details.append(f"{business['rating']}/5 on Yelp ({business.get('review_count', 0)} reviews)")
        if business.get("price"):
            details.append(business["price"])
        if categories:
            details.append(categories)
        if address:
            details.append(address)
        places.append({
            "title": business.get("name", "Local venue"),
            "url": business["url"],
            "snippet": " · ".join(details),
            "source": "Yelp",
        })
    return places


def search_restaurants(city: str, request: str) -> list[dict]:
    """Find individual Resy/OpenTable restaurant booking pages; this does not book a table."""
    query = f"restaurants in {city} {request} reservations (site:resy.com OR site:opentable.com)"
    cache = Path("cache/restaurants")
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / (hashlib.sha1(("v1" + query).encode()).hexdigest()[:12] + ".json")
    if path.exists():
        return json.loads(path.read_text())

    def normalize(hits: list[dict], url_key: str) -> list[dict]:
        found = []
        for h in hits:
            url = h.get(url_key, "")
            parsed = urlparse(url)
            host = parsed.netloc.lower().removeprefix("www.")
            if parsed.scheme != "https" or not (host == "resy.com" or host.endswith(".resy.com") or
                                                  host == "opentable.com" or host.endswith(".opentable.com")):
                continue
            path = parsed.path.strip("/")
            is_resy_host = host == "resy.com" or host.endswith(".resy.com")
            is_opentable_host = host == "opentable.com" or host.endswith(".opentable.com")
            is_resy_venue = is_resy_host and re.fullmatch(r"cities/[^/]+/venues/[^/]+", path, re.I)
            is_opentable_restaurant = is_opentable_host and re.fullmatch(r"r/[^/]+", path, re.I)
            if not (is_resy_venue or is_opentable_restaurant):
                continue
            snippets = h.get("snippets") or []
            snippet = snippets[0] if snippets else (h.get("snippet") or h.get("description") or "")
            found.append({
                "title": h.get("title", "Restaurant booking page"),
                "url": url,
                "snippet": snippet,
                "source": "Resy" if is_resy_host else "OpenTable",
            })
            if len(found) == 5:
                break
        return found

    results = []
    if os.getenv("SERPER_API_KEY"):
        try:
            import requests
            response = requests.post("https://google.serper.dev/search", json={"q": query, "num": 20},
                                     headers={"X-API-KEY": os.environ["SERPER_API_KEY"]}, timeout=10)
            response.raise_for_status()
            results = normalize(response.json().get("organic", []), "link")
        except Exception as e:  # noqa: BLE001 - try You.com next
            print(f"[serper] restaurant search failed: {e}")

    key = os.getenv("YOU_API_KEY") or os.getenv("YDC_API_KEY")
    if not results and key:
        try:
            import requests
            error = None
            for endpoint in ("https://ydc-index.io/v1/search", "https://api.ydc-index.io/search"):
                try:
                    response = requests.get(endpoint, params={"query": query}, headers={"X-API-Key": key}, timeout=10)
                    response.raise_for_status()
                    body = response.json()
                    hits = (body.get("results") or {}).get("web") or body.get("hits") or []
                    results = normalize(hits, "url")
                    break
                except Exception as e:  # noqa: BLE001 - try the legacy endpoint
                    error = e
            if not results and error:
                raise error
        except Exception as e:  # noqa: BLE001 - no fabricated restaurant listings
            print(f"[you.com] restaurant search failed: {e}")

    if results:
        path.write_text(json.dumps(results, indent=2))
    return results


def search_michelin_restaurants(city: str, request: str, limit: int = 5) -> list[dict]:
    """Find individual MICHELIN Guide restaurant pages through configured search APIs."""
    query = f'MICHELIN Guide restaurants in {city} {request} site:guide.michelin.com'

    def normalize(hits: list[dict], url_key: str) -> list[dict]:
        found = []
        for hit in hits:
            url = hit.get(url_key, "")
            parsed = urlparse(url)
            host = parsed.netloc.lower().removeprefix("www.")
            if parsed.scheme != "https" or host != "guide.michelin.com":
                continue
            if not re.search(r"(?:^|/)restaurant/[^/]+/?$", parsed.path, re.I):
                continue
            snippet = hit.get("snippet") or ""
            if not snippet and hit.get("snippets"):
                snippet = hit["snippets"][0]
            if not snippet:
                snippet = hit.get("description", "")
            found.append({
                "title": hit.get("title", "MICHELIN Guide restaurant"),
                "url": url,
                "snippet": snippet,
                "source": "MICHELIN Guide",
            })
            if len(found) >= limit:
                break
        return found

    if os.getenv("SERPER_API_KEY"):
        try:
            import requests

            response = requests.post(
                "https://google.serper.dev/search", json={"q": query, "num": 20},
                headers={"X-API-KEY": os.environ["SERPER_API_KEY"]}, timeout=10,
            )
            response.raise_for_status()
            found = normalize(response.json().get("organic", []), "link")
            if found:
                return found
        except Exception as exc:  # noqa: BLE001 - try You.com fallback
            print(f"[serper] MICHELIN restaurant search failed: {type(exc).__name__}")

    key = os.getenv("YOU_API_KEY") or os.getenv("YDC_API_KEY")
    if key:
        try:
            import requests

            last_error = None
            for endpoint in ("https://ydc-index.io/v1/search", "https://api.ydc-index.io/search"):
                try:
                    response = requests.get(
                        endpoint, params={"query": query}, headers={"X-API-Key": key}, timeout=10
                    )
                    response.raise_for_status()
                    body = response.json()
                    hits = (body.get("results") or {}).get("web") or body.get("hits") or []
                    return normalize(hits, "url")
                except Exception as exc:  # noqa: BLE001 - support both You.com API versions
                    last_error = exc
            if last_error:
                print(f"[you.com] MICHELIN restaurant search failed: {type(last_error).__name__}")
        except Exception as exc:  # noqa: BLE001 - optional search source
            print(f"[you.com] MICHELIN restaurant search failed: {type(exc).__name__}")
    return []


def check_popular_times(title: str, city: str, weekday: str, hour: int) -> dict | None:
    """Return a venue's typical Google Maps busyness score via SerpApi, if available.

    This is a weekday/hour average, not a forecast for a particular date. No result
    is returned if the venue cannot be matched confidently or has no Popular Times.
    """
    key = os.getenv("SERPAPI_API_KEY")
    if not key:
        return None

    import requests

    endpoint = "https://serpapi.com/search.json"
    response = requests.get(endpoint, params={
        "engine": "google_maps", "type": "search", "q": f"{title} {city}",
        "hl": "en", "api_key": key,
    }, timeout=15)
    response.raise_for_status()
    results = response.json().get("local_results", [])
    wanted = re.sub(r"[^a-z0-9 ]", " ", title.lower())
    wanted_tokens = {token for token in wanted.split() if len(token) > 2}

    def match_score(place: dict) -> float:
        candidate = re.sub(r"[^a-z0-9 ]", " ", place.get("title", "").lower())
        tokens = {token for token in candidate.split() if len(token) > 2}
        overlap = len(wanted_tokens & tokens) / max(1, len(wanted_tokens))
        return max(overlap, SequenceMatcher(None, wanted, candidate).ratio())

    place = max(results, key=match_score, default=None)
    if not place or match_score(place) < 0.55:
        return None

    place_id = place.get("place_id")
    params = {"engine": "google_maps", "type": "place", "hl": "en", "api_key": key}
    if place_id:
        params["place_id"] = place_id
    else:
        data_id = place.get("data_id")
        coords = place.get("gps_coordinates") or {}
        if not data_id or coords.get("latitude") is None or coords.get("longitude") is None:
            return None
        params["data"] = f"!4m5!3m4!1s{data_id}!8m2!3d{coords['latitude']}!4d{coords['longitude']}"

    response = requests.get(endpoint, params=params, timeout=15)
    response.raise_for_status()
    popular = (response.json().get("place_results") or {}).get("popular_times") or {}
    hourly = (popular.get("graph_results") or {}).get(weekday.lower(), [])
    target_hour = hour % 12 or 12
    suffix = "AM" if hour < 12 else "PM"
    expected = f"{target_hour} {suffix}"
    bucket = next((entry for entry in hourly if entry.get("time", "").upper() == expected), None)
    score = bucket.get("busyness_score") if bucket else None
    if not isinstance(score, (int, float)):
        return None
    return {"score": int(score), "place": place.get("title", title)}
