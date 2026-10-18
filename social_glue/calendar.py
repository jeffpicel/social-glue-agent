"""Calendar invites for confirmed plans: a one-tap Google Calendar link, unless the event has its own page."""
from datetime import datetime, timedelta
from urllib.parse import urlencode, urlparse

DAYS = ["Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays", "Sundays"]
OFFICIAL = ("lu.ma", "luma.com", "partiful.com", "eventbrite.com", "meetup.com")
TZ = "America/Los_Angeles"


def next_date(day: str, after: datetime) -> datetime:
    """The next `day` (e.g. "Tuesdays") on or after `after`'s date."""
    return after + timedelta(days=(DAYS.index(day) - after.weekday()) % 7)


def invite(plan: dict, confirmed_ts: str, attendees: list[str]) -> str | None:
    """Message text with an invite for a confirmed plan, or None if we don't know when it is."""
    url = plan.get("url") or ""
    host = urlparse(url).netloc.lower().removeprefix("www.")
    if url and any(host == h or host.endswith("." + h) for h in OFFICIAL):
        return f"RSVP and add it to your calendar on the official page: {url}"
    if not plan.get("day") or plan.get("start") is None:
        return None
    now = datetime.fromisoformat(confirmed_ts)
    start = next_date(plan["day"], now).replace(hour=plan["start"] // 60, minute=plan["start"] % 60, second=0, microsecond=0)
    if start <= now:  # that day's time already passed: next week
        start += timedelta(days=7)
    end = start + timedelta(minutes=plan.get("minutes") or 60)
    title = plan["option"].split(" (")[0]
    details = f"Planned by Glue in the group chat. Going: {', '.join(attendees)}." + (f"\n{url}" if url else "")
    link = "https://calendar.google.com/calendar/render?" + urlencode({
        "action": "TEMPLATE", "text": title[:1].upper() + title[1:],
        "dates": f"{start:%Y%m%dT%H%M%S}/{end:%Y%m%dT%H%M%S}", "ctz": TZ, "details": details,
    })
    return f"Add it to your calendar ({start:%a %b %-d, %-I:%M%p}): {link}"
