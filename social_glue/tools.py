"""Event search (Serper/Google first, then You.com), cached to disk so the demo never stalls on the network."""
import hashlib
import json
import os
import re
from difflib import SequenceMatcher
from datetime import date
from pathlib import Path
from time import time
from urllib.parse import urlparse

CACHE = Path("cache/events")
SOURCE_REGISTRY = CACHE.parent / "search_sources.json"
EVENT_CACHE_TTL_SECONDS = 6 * 60 * 60
SOURCE_DISCOVERY_INTERVAL = 3

DEFAULT_EVENT_SOURCES = {
    "lu.ma": "Luma",
    "partiful.com": "Partiful",
    "eventbrite.com": "Eventbrite",
    "cerebralvalley.ai": "Cerebral Valley",
    "sf.funcheap.com": "Funcheap",
    "todaytix.com": "TodayTix",
    "ticketmaster.com": "Ticketmaster",
    "stubhub.com": "StubHub",
    "vividseats.com": "Vivid Seats",
}
BLOCKED_EVENT_DOMAINS = {
    "google.com", "bing.com", "facebook.com", "instagram.com", "youtube.com",
    "tiktok.com", "reddit.com", "yelp.com", "wikipedia.org",
}
EVENT_PAGE_SIGNAL = re.compile(
    r"\b(?:event|concert|show|ticket|festival|workshop|class|comedy|music|hackathon|"
    r"theatre|theater|exhibition|tour|match|race|market|party|conference|meetup)\b",
    re.I,
)
SOURCE_INTENT = re.compile(r"\b(?:search|check|look|find|use|try|add|include)\b.{0,50}\b(?:site|source|website|events?|tickets?)\b|\b(?:site|source|website)\b.{0,50}\b(?:search|check|use|try|add|include)\b", re.I)
URL_IN_MESSAGE = re.compile(r"(?:https?://)?(?:www\.)?(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s<>]*)?", re.I)
VENUE_CONTEXT = re.compile(r"\b(?:venue|venues|restaurant|restaurants|bar|bars|cafe|cafes|coffee shop|place|places|spot|spots|dinner|brunch|lunch|show|concert|event|theater|theatre|museum|club|eat)\b", re.I)
VENUE_CACHE_TTL_SECONDS = 30 * 24 * 60 * 60
VENUE_REFERENCE_DOMAINS = {
    "yelp.com", "opentable.com", "resy.com", "google.com", "maps.google.com",
    "instagram.com", "facebook.com", "tripadvisor.com", "foursquare.com",
}

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


def _source_host(url: str) -> str:
    host = urlparse(url).netloc.lower().split("@")[-1].split(":")[0]
    return host.removeprefix("www.")


def _known_source(host: str, sources: dict) -> str | None:
    matches = [domain for domain in sources if host == domain or host.endswith("." + domain)]
    return max(matches, key=len) if matches else None


def _load_source_registry() -> dict:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    initial = {
        "searches": 0,
        "sources": {
            domain: {"label": label, "enabled": True, "successes": 0, "last_seen": None}
            for domain, label in DEFAULT_EVENT_SOURCES.items()
        },
        "candidates": {},
    }
    try:
        state = json.loads(SOURCE_REGISTRY.read_text())
        if (not isinstance(state, dict) or not isinstance(state.get("sources", {}), dict)
                or not isinstance(state.get("candidates", {}), dict)):
            return initial
    except (OSError, json.JSONDecodeError):
        return initial

    state.setdefault("searches", 0)
    state.setdefault("sources", {})
    state.setdefault("candidates", {})
    for domain, label in DEFAULT_EVENT_SOURCES.items():
        state["sources"].setdefault(
            domain, {"label": label, "enabled": True, "successes": 0, "last_seen": None}
        )
    return state


def _write_source_registry(state: dict) -> None:
    tmp = SOURCE_REGISTRY.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    tmp.replace(SOURCE_REGISTRY)


def observe_search_sources(message: dict) -> None:
    """Review every incoming group message for event-search source links and update the registry."""
    text = str(message.get("text", ""))
    state = _load_source_registry()
    state["messages_checked"] = int(state.get("messages_checked", 0)) + 1
    state["last_message_checked"] = message.get("ts")
    message_id = hashlib.sha1(
        f"{message.get('name', '')}|{message.get('ts', '')}|{text}".encode()
    ).hexdigest()[:16]
    explicit_source_intent = bool(SOURCE_INTENT.search(text))

    for raw_url in URL_IN_MESSAGE.findall(text):
        url = raw_url.rstrip(".,!?;:)]}")
        if not urlparse(url).scheme:
            url = "https://" + url
        host = _source_host(url)
        if (urlparse(url).scheme != "https" or not host
                or any(host == domain or host.endswith("." + domain) for domain in BLOCKED_EVENT_DOMAINS)
                or _known_source(host, state["sources"])
                or not (explicit_source_intent or EVENT_PAGE_SIGNAL.search(text + " " + url))):
            continue

        candidate = state["candidates"].setdefault(host, {
            "label": host, "searches_seen": [], "messages_seen": [], "successes": 0,
            "last_seen": date.today().isoformat(),
        })
        messages_seen = candidate.setdefault("messages_seen", [])
        if message_id not in messages_seen:
            messages_seen.append(message_id)
        candidate["last_seen"] = date.today().isoformat()
        # An explicit request to use a source is enough; incidental event links need repeat evidence.
        if explicit_source_intent or len(messages_seen) >= 2:
            state["sources"][host] = {
                "label": candidate.get("label", host), "enabled": True,
                "successes": int(candidate.get("successes", 0)),
                "last_seen": candidate["last_seen"], "discovered": True,
            }
            del state["candidates"][host]

    _write_source_registry(state)


def _venue_cache_path(group_id: str) -> Path:
    group_key = hashlib.sha1(str(group_id).encode()).hexdigest()[:16]
    return CACHE.parent / "groups" / group_key / "venues.json"


def _venue_cache_read(path: Path) -> dict:
    try:
        venues = json.loads(path.read_text())
        return venues if isinstance(venues, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _venue_search_hits(name: str, city: str) -> list[dict]:
    """Look up an exact venue with configured public search providers, Serper first."""
    query = f'"{name}" {city} official website venue'
    hits = []
    if os.getenv("SERPER_API_KEY"):
        try:
            import requests
            response = requests.post(
                "https://google.serper.dev/search", json={"q": query, "num": 10},
                headers={"X-API-KEY": os.environ["SERPER_API_KEY"]}, timeout=8,
            )
            response.raise_for_status()
            hits = response.json().get("organic", [])
        except Exception:  # noqa: BLE001 - try You.com next
            pass
    key = os.getenv("YOU_API_KEY") or os.getenv("YDC_API_KEY")
    if not hits and key:
        try:
            import requests
            for endpoint in ("https://ydc-index.io/v1/search", "https://api.ydc-index.io/search"):
                try:
                    response = requests.get(endpoint, params={"query": query},
                                            headers={"X-API-Key": key}, timeout=8)
                    response.raise_for_status()
                    body = response.json()
                    hits = (body.get("results") or {}).get("web") or body.get("hits") or []
                    if hits:
                        break
                except Exception:  # noqa: BLE001 - support both You.com API versions
                    continue
        except Exception:  # noqa: BLE001 - venue caching must not block chat handling
            return []
    return hits


def _resolve_venue(name: str, city: str) -> dict:
    hits = _venue_search_hits(name, city)
    candidates = []
    for hit in hits:
        url = hit.get("link") or hit.get("url") or ""
        parsed = urlparse(url)
        host = _source_host(url)
        if parsed.scheme != "https" or not host or not parsed.path.strip("/"):
            continue
        if any(host == domain or host.endswith("." + domain) for domain in VENUE_REFERENCE_DOMAINS):
            kind = "reference"
        else:
            kind = "website_candidate"
        candidates.append({
            "title": hit.get("title", ""), "url": url,
            "snippet": hit.get("snippet") or hit.get("description") or "", "kind": kind,
        })
    direct = next((item for item in candidates if item["kind"] == "website_candidate"), None)
    if not candidates and os.getenv("YELP_API_KEY"):
        try:
            for place in search_yelp_places(city, name, limit=5):
                similarity = SequenceMatcher(None, name.casefold(), place["title"].casefold()).ratio()
                if similarity >= 0.55:
                    candidates.append({
                        "title": place["title"], "url": place["url"],
                        "snippet": place["snippet"], "kind": "reference",
                    })
        except Exception:  # noqa: BLE001 - venue caching must not block chat handling
            pass
    return {
        "website": direct["url"] if direct else None,
        "website_title": direct["title"] if direct else None,
        "references": candidates[:5],
        "lookup_status": "found" if candidates else ("not_found" if hits else "pending"),
    }


def observe_chat_venues(message: dict, city: str = "San Francisco", group_id: str = "default") -> None:
    """Extract named venues mentioned in chat, look up their sites, and retain them locally."""
    text = str(message.get("text", "")).strip()
    # Most ordinary chat is skipped; venue-like wording or a multi-item list triggers extraction.
    list_like = bool(
        "," in text
        or re.search(r"\b(?:let'?s|try|go to|check out|what about|maybe)\b[^.?!]{0,70}\b(?:and|or)\b", text, re.I)
    )
    if not text or not (VENUE_CONTEXT.search(text) or list_like):
        return

    from social_glue import llm
    try:
        extracted = llm.chat(
            "Extract only specifically named real-world venues from this group-chat message. "
            "A venue is a restaurant, bar, cafe, event space, museum, theater, club, or named event location. "
            "Exclude people, cities, neighborhoods, generic categories, and hypothetical examples. "
            "Return JSON as {\"venues\":[{\"name\":\"...\",\"city\":\"... or empty\"}]}; "
            "return an empty list when no venue is named.",
            f"GROUP LOCATION: {city}\nMESSAGE: {text}",
            tier="fast", json_mode=True, fake=lambda: {"venues": []},
        )
    except Exception:  # noqa: BLE001 - extraction should never interrupt chat handling
        return
    entries = extracted.get("venues", []) if isinstance(extracted, dict) else []
    if not isinstance(entries, list):
        return

    cache_path = _venue_cache_path(group_id)
    cache = _venue_cache_read(cache_path)
    now = time()
    for entry in entries[:8]:
        if isinstance(entry, str):
            name, entry_city = entry.strip(), ""
        elif isinstance(entry, dict):
            name = str(entry.get("name", "")).strip()
            entry_city = str(entry.get("city", "")).strip()
        else:
            continue
        if not name or len(name) > 100:
            continue
        location = entry_city or city or "Unknown"
        key = hashlib.sha1(f"{name.casefold()}|{location.casefold()}".encode()).hexdigest()[:16]
        venue = cache.setdefault(key, {
            "name": name, "city": location, "website": None, "website_title": None,
            "references": [], "lookup_status": "pending", "mentions": 0,
            "first_seen": message.get("ts"),
        })
        venue["mentions"] = int(venue.get("mentions", 0)) + 1
        venue["last_seen"] = message.get("ts")
        checked = float(venue.get("last_checked", 0) or 0)
        if (not venue.get("website") and now - checked >= VENUE_CACHE_TTL_SECONDS
                and (os.getenv("SERPER_API_KEY") or os.getenv("YOU_API_KEY")
                     or os.getenv("YDC_API_KEY") or os.getenv("YELP_API_KEY"))):
            venue.update(_resolve_venue(name, location))
            venue["last_checked"] = now

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, indent=2, sort_keys=True) + "\n")
    tmp.replace(cache_path)


def seed_chat_venues(group_id: str, venues: list[tuple[str, str]]) -> Path:
    """Add a curated (venue, city) list to one group's cache and resolve links when configured."""
    cache_path = _venue_cache_path(group_id)
    cache = _venue_cache_read(cache_path)
    now = time()
    for name, city in venues:
        key = hashlib.sha1(f"{name.casefold()}|{city.casefold()}".encode()).hexdigest()[:16]
        venue = cache.setdefault(key, {
            "name": name, "city": city, "website": None, "website_title": None,
            "references": [], "lookup_status": "pending", "mentions": 0,
            "first_seen": "seed", "seeded": True,
        })
        venue["seeded"] = True
        venue["last_seen"] = "seed"
        if not venue.get("website") and (os.getenv("SERPER_API_KEY") or os.getenv("YOU_API_KEY")
                                          or os.getenv("YDC_API_KEY") or os.getenv("YELP_API_KEY")):
            venue.update(_resolve_venue(name, city))
            venue["last_checked"] = now
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, indent=2, sort_keys=True) + "\n")
    tmp.replace(cache_path)
    return cache_path


def _normalize_event_results(hits: list[dict], url_key: str, sources: dict, allow_new: bool) -> list[dict]:
    today = date.today()
    results, seen_urls = [], set()
    for hit in hits:
        url = hit.get(url_key, "")
        parsed = urlparse(url)
        host = _source_host(url)
        path = parsed.path.strip("/")
        title = hit.get("title", "")
        snippets = hit.get("snippets") or []
        snippet = hit.get("snippet") or (snippets[0] if snippets else hit.get("description", ""))
        if (parsed.scheme != "https" or not host or not path
                or any(host == domain or host.endswith("." + domain) for domain in BLOCKED_EVENT_DOMAINS)
                or LISTING.search(url + " " + title)
                or _is_past(" ".join(str(hit.get(k) or "") for k in ("date", "title", "snippet", "description")), today)
                or url in seen_urls):
            continue

        known = _known_source(host, sources)
        if not known and (not allow_new or not EVENT_PAGE_SIGNAL.search(f"{url} {title} {snippet}")):
            continue
        source_domain = known or host
        label = (sources.get(source_domain) or {}).get("label") or source_domain
        results.append({
            "title": title,
            "url": url,
            "snippet": " ".join(str(x) for x in (hit.get("date"), snippet) if x),
            "source": label,
            "source_domain": source_domain,
        })
        seen_urls.add(url)
        if len(results) == 5:
            break
    return results


def _serper(query: str, source_domains: list[str] | None, sources: dict, allow_new: bool) -> list[dict]:
    """Search event pages; periodic broad searches discover additional source domains."""
    import requests

    q = query
    if source_domains:
        q += " (" + " OR ".join(f"site:{domain}" for domain in source_domains) + ")"
    response = requests.post(
        "https://google.serper.dev/search", json={"q": q, "num": 20},
        headers={"X-API-KEY": os.environ["SERPER_API_KEY"]}, timeout=10,
    )
    response.raise_for_status()
    return _normalize_event_results(response.json().get("organic", []), "link", sources, allow_new)


def _record_event_sources(state: dict, results: list[dict], query: str) -> None:
    query_id = hashlib.sha1(query.lower().encode()).hexdigest()[:12]
    domains = {item.get("source_domain") for item in results if item.get("source_domain")}
    now = date.today().isoformat()
    for domain in domains:
        if domain in state["sources"]:
            source = state["sources"][domain]
            source["successes"] = int(source.get("successes", 0)) + 1
            source["last_seen"] = now
            continue

        candidate = state["candidates"].setdefault(domain, {
            "label": domain, "searches_seen": [], "messages_seen": [], "successes": 0, "last_seen": now,
        })
        candidate.setdefault("messages_seen", [])
        if query_id not in candidate["searches_seen"]:
            candidate["searches_seen"].append(query_id)
            candidate["successes"] = int(candidate.get("successes", 0)) + 1
        candidate["last_seen"] = now
        # Promote only after the domain returns event-like pages for two distinct queries.
        if len(candidate["searches_seen"]) >= 2 or len(candidate["messages_seen"]) >= 2:
            state["sources"][domain] = {
                "label": candidate["label"], "enabled": True,
                "successes": candidate["successes"], "last_seen": now,
                "discovered": True,
            }
            del state["candidates"][domain]


def search_events(city: str, interests: str, when: str = "this month") -> list[dict]:
    state = _load_source_registry()
    sources = state["sources"]
    active = sorted(
        ((domain, data) for domain, data in sources.items() if data.get("enabled", True)),
        key=lambda pair: (-int(pair[1].get("successes", 0)), pair[0]),
    )
    source_domains = [domain for domain, _ in active]
    source_terms = " OR ".join(data.get("label", domain) for domain, data in active)
    broad_discovery = (int(state.get("searches", 0)) + 1) % SOURCE_DISCOVERY_INTERVAL == 0
    context = f"events in {city} {when} for people into {interests}"
    query = f"{context} date time official event tickets" if broad_discovery else f"{context} ({source_terms}) date time"

    CACHE.mkdir(parents=True, exist_ok=True)
    cache_identity = json.dumps({"v": 7, "query": query, "sources": source_domains, "discovery": broad_discovery}, sort_keys=True)
    path = CACHE / (hashlib.sha1(cache_identity.encode()).hexdigest()[:12] + ".json")
    if path.exists() and time() - path.stat().st_mtime < EVENT_CACHE_TTL_SECONDS:
        return json.loads(path.read_text())

    results = []
    if os.getenv("SERPER_API_KEY"):
        try:
            results = _serper(query, None if broad_discovery else source_domains, sources, broad_discovery)
        except Exception as exc:  # noqa: BLE001 - fall through to You.com
            print(f"[serper] event search failed: {type(exc).__name__}")

    key = os.getenv("YOU_API_KEY") or os.getenv("YDC_API_KEY")
    if not results and key:
        import requests

        last_error = None
        for endpoint in ("https://ydc-index.io/v1/search", "https://api.ydc-index.io/search"):
            try:
                response = requests.get(endpoint, params={"query": query}, headers={"X-API-Key": key}, timeout=10)
                response.raise_for_status()
                body = response.json()
                hits = (body.get("results") or {}).get("web") or body.get("hits") or []
                results = _normalize_event_results(hits, "url", sources, broad_discovery)
                if results:
                    break
            except Exception as exc:  # noqa: BLE001 - support both You.com API versions
                last_error = exc
        if not results and last_error:
            print(f"[you.com] event search failed: {type(last_error).__name__}")

    state["searches"] = int(state.get("searches", 0)) + 1
    _record_event_sources(state, results, query)
    _write_source_registry(state)
    if results:
        path.write_text(json.dumps(results, indent=2))
        return results
    return FALLBACK


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
