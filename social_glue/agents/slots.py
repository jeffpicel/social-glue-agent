"""Free-time windows at 15-minute resolution, mapped from chat (no calendar).

The listener stores weekly windows per person as the fact `free_times`, e.g. "Tuesdays 18:00-21:00, Saturdays 10:00-12:30".
A day that only appears in `availability` ("free Tuesdays") counts as a default evening window.
best_start() finds, for a day, the 15-minute start where the most people are free for the whole call.
"""
import re

from social_glue.brain import Brain

STEP = 15
DEFAULT_WINDOW = (19 * 60, 22 * 60)  # "free Tuesdays" with no time: assume the evening, so calls default to 7pm
WINDOW = re.compile(r"([A-Z][a-z]+days)\s+(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})")


def _split(v: str) -> list[str]:
    return [x.strip() for x in v.split(",") if x.strip()]


def windows(brain: Brain, person: str) -> dict[str, list[tuple[int, int]]]:
    """Day -> [(start_min, end_min)] for one person, minus days they said they can't do."""
    f = brain.facts(person)
    out: dict[str, list[tuple[int, int]]] = {}
    for m in WINDOW.finditer(f.get("free_times", {}).get("value", "")):
        day, h1, m1, h2, m2 = m.groups()
        out.setdefault(day, []).append((int(h1) * 60 + int(m1), int(h2) * 60 + int(m2)))
    for day in _split(f.get("availability", {}).get("value", "")):
        out.setdefault(day, [DEFAULT_WINDOW])
    for day in _split(f.get("unavailable", {}).get("value", "")):
        out.pop(day, None)
    return out


def best_start(brain: Brain, day: str, minutes: int = 60) -> tuple[int, int]:
    """(start_min, people_free) for the 15-minute start on `day` that the most people can make."""
    per_person = [windows(brain, p).get(day, []) for p in brain.people()]
    best = (DEFAULT_WINDOW[0], 0)
    for start in range(7 * 60, 23 * 60 - minutes + 1, STEP):
        n = sum(1 for ws in per_person if any(a <= start and start + minutes <= b for a, b in ws))
        if n > best[1]:
            best = (start, n)
    return best


def fmt(minute: int) -> str:
    h, m = divmod(minute, 60)
    return f"{(h - 1) % 12 + 1}{':%02d' % m if m else ''}{'am' if h < 12 else 'pm'}"


def free_for(brain: Brain, day: str, start: int, minutes: int) -> tuple[int, int]:
    """(people free for the whole slot, people we have any window for on that day)."""
    per_person = [windows(brain, p).get(day) for p in brain.people()]
    known = [ws for ws in per_person if ws]
    return sum(1 for ws in known if any(a <= start and start + minutes <= b for a, b in ws)), len(known)
