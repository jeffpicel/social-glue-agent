"""Find restaurant listings without claiming unverified seat availability.

The consumer booking pages are public, but this bot has no authorized live inventory
integration. A search result or booking link is not evidence that a requested slot is open.
"""
import os
import re
from datetime import date, datetime, timedelta

from social_glue.brain import Brain
from social_glue.agents import slots
from social_glue.tools import (
    check_popular_times,
    record_group_search,
    search_michelin_restaurants,
    search_restaurants,
    search_yelp_places,
)

REQUEST = re.compile(
    r"\b(?:reservation|reservations|reserve|book\s+(?:us\s+)?(?:a\s+)?(?:table|restaurant|dinner)|"
    r"find\s+(?:us\s+)?(?:a\s+)?restaurant|where\s+should\s+we\s+eat|restaurant\s+recommendations?)\b",
    re.I,
)


def is_request(text: str) -> bool:
    return bool(REQUEST.search(text))


def respond(brain: Brain, msg: dict, transcript: list[dict] | None = None, group_id: str = "default") -> str:
    """Infer dinner details and only suggest venues with a checked typical crowd level."""
    request = msg["text"]
    group = brain.facts("group")
    city = group.get("location", {}).get("value", "San Francisco")
    party_size = infer_party_size(brain, request)
    day, time, date_source, time_source = infer_date_and_time(brain, request, msg["ts"], transcript)
    search_request = f"{request}; {day.isoformat()} at {time}; party of {party_size}"
    options = search_restaurants(city, search_request, group_id=group_id)
    record_group_search(group_id, "restaurants", search_request, options, city)
    try:
        yelp_places = search_yelp_places(city, f"restaurants {request}", limit=5)
    except Exception as exc:  # noqa: BLE001 - Yelp is an optional discovery source
        print(f"[yelp] restaurant search failed: {type(exc).__name__}")
        yelp_places = []
    record_group_search(group_id, "venues", f"restaurants {request}", yelp_places, city)
    try:
        michelin_places = search_michelin_restaurants(city, search_request, limit=5)
    except Exception as exc:  # noqa: BLE001 - Michelin search is an optional discovery source
        print(f"[michelin] restaurant search failed: {type(exc).__name__}")
        michelin_places = []
    record_group_search(group_id, "restaurants", f"MICHELIN {search_request}", michelin_places, city)
    seen = {item["title"].casefold() for item in options}
    for item in yelp_places + michelin_places:
        if item["title"].casefold() not in seen:
            options.append(item)
            seen.add(item["title"].casefold())
    if not options:
        return (
            f"I couldn't find a restaurant listing for {city} from Resy, OpenTable, Yelp, or the MICHELIN Guide. "
            "I haven't checked table availability or made a reservation."
        )

    # Popular Times is a typical weekday/hour pattern, not a date-specific forecast.
    # Fail closed: don't suggest venues when crowd data could not be checked.
    parsed_minutes = _parse_time(time)
    hour = (parsed_minutes if parsed_minutes is not None else 19 * 60) // 60
    checked = []
    for item in options:
        try:
            crowd = check_popular_times(item["title"], city, day.strftime("%A"), hour)
        except Exception as exc:  # noqa: BLE001 - a crowd lookup must not crash the bot
            print(f"[popular-times] lookup failed: {type(exc).__name__}")
            crowd = None
        if crowd:
            checked.append((item, crowd))
    if not checked:
        if not os.getenv("SERPAPI_API_KEY"):
            reason = "Popular Times checking isn't configured (set SERPAPI_API_KEY)."
        else:
            reason = "I couldn't match these restaurants to Google Maps Popular Times data."
        return (
            f"I found restaurant listings in {city}, but {reason} "
            "I won't suggest a venue until I can check its typical crowd level for that weekday and time."
        )
    checked.sort(key=lambda pair: pair[1]["score"])

    lines = [
        f"I checked Google Maps Popular Times for these venues in {city} for {day.strftime('%A')} around {time} "
        f"(planning for {day.strftime('%A, %b %-d')}; inferred from {date_source} date and {time_source} time), "
        f"party of {party_size}:"
    ]
    for item, crowd in checked[:3]:
        title = " ".join(item["title"].split())
        snippet = " ".join(item["snippet"].split())
        lines.append(
            f"• {title}" + (f" — {snippet}" if snippet else "")
            + f"\n  Source: {item.get('source', 'restaurant search')}"
            + f"\n  Typical busyness at that hour: {crowd['score']}/100"
            + f"\n  Details: {item['url']}"
        )
    lines.append(
        "The crowd score is Google's typical busyness pattern for that weekday/hour, not a forecast for that exact "
        "date. These listings do not confirm reservation openings; check the restaurant's booking provider for the "
        "requested date, time, and party size. No reservation has been made."
    )
    return "\n".join(lines)


WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def infer_date_and_time(
    brain: Brain, text: str, timestamp: str, transcript: list[dict] | None = None
) -> tuple[date, str, str, str]:
    """Prefer a date/time in the request; otherwise use shared schedule or a dinner default."""
    now = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    today = now.date()
    parsed_day = _parse_date(text, today)
    date_source = "request" if parsed_day else "schedule/default"
    parsed_time = _parse_time(text)
    time_source = "request" if parsed_time is not None else "schedule/default"

    # If the request omits a field, reuse recent positive planning context before
    # falling back to the group's saved weekly availability.
    for prior in reversed((transcript or [])[-8:]):
        if prior.get("name", "").lower() == "glue":
            continue
        prior_text = prior.get("text", "")
        if re.search(r"\b(?:can't|cannot|not free|busy|unavailable|class|work late)\b", prior_text, re.I):
            continue
        if parsed_day is None:
            prior_ts = prior.get("ts", timestamp)
            prior_today = datetime.fromisoformat(prior_ts.replace("Z", "+00:00")).date()
            parsed_day = _parse_date(prior_text, prior_today)
            if parsed_day:
                date_source = "recent chat"
        if parsed_time is None:
            parsed_time = _parse_time(prior_text)
            if parsed_time is not None:
                time_source = "recent chat"
        if parsed_day is not None and parsed_time is not None:
            break

    if parsed_day is None:
        parsed_day = _best_scheduled_date(brain, today) or _next_weekday(today, 4)  # Friday
    if parsed_time is None:
        parsed_time = _best_scheduled_time(brain, parsed_day.weekday()) or 19 * 60
    return parsed_day, _format_time(parsed_time), date_source, time_source


def _parse_date(text: str, today: date) -> date | None:
    lower = text.lower()
    if re.search(r"\b(?:today|tonight)\b", lower):
        return today
    if re.search(r"\btomorrow\b", lower):
        return today + timedelta(days=1)

    weekday = re.search(
        r"\b(?:(?:this|next)\s+)?(mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|"
        r"thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)\b",
        lower,
    )
    if weekday:
        prefix = lower[max(0, weekday.start() - 5):weekday.start()]
        target = next(i for i, name in enumerate(WEEKDAYS) if name.lower().startswith(weekday.group(1)[:3]))
        delta = (target - today.weekday()) % 7
        if delta == 0 and "next" in prefix:
            delta = 7
        return today + timedelta(days=delta)

    iso = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
    if iso:
        try:
            return date.fromisoformat(iso.group(1))
        except ValueError:
            return None
    slash = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", text)
    if slash:
        month, day = int(slash.group(1)), int(slash.group(2))
        year = int(slash.group(3)) if slash.group(3) else today.year
        if year < 100:
            year += 2000
        try:
            candidate = date(year, month, day)
            return candidate if slash.group(3) or candidate >= today else candidate.replace(year=year + 1)
        except ValueError:
            return None
    named = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:,?\s+(20\d{2}))?\b", lower)
    if named:
        month = next(i for i, name in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1) if name == named.group(1)[:3])
        year = int(named.group(3)) if named.group(3) else today.year
        try:
            candidate = date(year, month, int(named.group(2)))
            return candidate if named.group(3) or candidate >= today else candidate.replace(year=year + 1)
        except ValueError:
            return None
    return None


def _parse_time(text: str) -> int | None:
    lower = text.lower()
    if re.search(r"\bnoon\b", lower):
        return 12 * 60
    if re.search(r"\bmidnight\b", lower):
        return 0
    # Handles both "7pm" and ranges such as "6-8 pm" by selecting the range start.
    match = re.search(r"\b(?:at|around|from|between)?\s*(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)\b", lower)
    if match:
        hour, minute = int(match.group(1)), int(match.group(2) or 0)
        hour = hour % 12 + (12 if match.group(3).startswith("p") else 0)
        return hour * 60 + minute
    bare = re.search(r"\b(?:at|around|from|between)\s+(\d{1,2})(?::(\d{2}))?\b", lower)
    if bare:
        hour, minute = int(bare.group(1)), int(bare.group(2) or 0)
        if 1 <= hour <= 11:
            hour += 12  # A bare hour for dinner is interpreted as evening.
        return hour * 60 + minute
    return None


def _next_weekday(today: date, weekday: int) -> date:
    delta = (weekday - today.weekday()) % 7 or 7
    return today + timedelta(days=delta)


def _best_scheduled_date(brain: Brain, today: date) -> date | None:
    candidates = []
    for offset in range(1, 15):
        candidate = today + timedelta(days=offset)
        start, attendees = _best_dinner_start(brain, candidate.weekday())
        if attendees:
            candidates.append((-attendees, offset, candidate))
    return min(candidates)[2] if candidates else None


def _best_scheduled_time(brain: Brain, weekday: int) -> int | None:
    start, attendees = _best_dinner_start(brain, weekday)
    return start if attendees else None


def _best_dinner_start(brain: Brain, weekday: int) -> tuple[int, int]:
    day = WEEKDAYS[weekday] + "s"
    known = [slots.windows(brain, person).get(day, []) for person in brain.people()]
    known = [windows for windows in known if windows]
    if not known:
        return 19 * 60, 0
    starts = range(17 * 60, 21 * 60 + 1, 15)
    scored = [
        (sum(any(a <= start and start + 60 <= b for a, b in windows) for windows in known), start)
        for start in starts
    ]
    max_count = max(count for count, _ in scored)
    if max_count == 0:
        return 19 * 60, 0
    # Among equally available options, choose the one closest to the usual 7pm dinner time.
    return min((start for count, start in scored if count == max_count), key=lambda start: (abs(start - 19 * 60), start)), max_count


def _format_time(minutes: int) -> str:
    hour, minute = divmod(minutes, 60)
    suffix = "am" if hour < 12 else "pm"
    hour12 = hour % 12 or 12
    return f"{hour12}:{minute:02d}{suffix}" if minute else f"{hour12}{suffix}"


_PARTY_SIZE = re.compile(
    r"\b(?:party\s+of|table\s+for|dinner\s+for|reservation\s+for|for)\s+"
    r"(\d{1,2})(?!\s*(?:a\.?m\.?|p\.?m\.?))\b|"
    r"\b(\d{1,2})\s*(?:people|guests|diners|covers|of\s+us)\b",
    re.I,
)
_PARTY_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


def _has_explicit_party_size(text: str) -> bool:
    return bool(_PARTY_SIZE.search(text) or re.search(
        r"\b(?:party\s+of|table\s+for|dinner\s+for|reservation\s+for|for)\s+(?:one|two|three|four|five|six|seven|eight|nine|ten)\b",
        text,
        re.I,
    ))


def infer_party_size(brain: Brain, text: str) -> int:
    """Use an explicit count, clear wording, or known group membership, in that order."""
    match = _PARTY_SIZE.search(text)
    if match:
        return max(1, int(match.group(1) or match.group(2)))

    word_count = re.search(
        r"\b(?:party\s+of|table\s+for|dinner\s+for|reservation\s+for|for)\s+(one|two|three|four|five|six|seven|eight|nine|ten)\b",
        text,
        re.I,
    )
    if word_count:
        return _PARTY_WORDS[word_count.group(1).lower()]
    if re.search(r"\b(?:just me|solo|for myself|one person)\b", text, re.I):
        return 1
    if re.search(r"\b(?:my partner|my date|both of us|my (?:wife|husband|spouse))\b", text, re.I):
        return 2

    # Brain profiles represent people who have participated in this group chat.
    # If only the requester is known, assume dinner for two (requester plus one guest).
    return max(2, len(brain.people()))
