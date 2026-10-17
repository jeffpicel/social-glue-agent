"""Interest sliders: the group's current appetite for each kind of hangout, learned explore/exploit style.

brain/interests.md holds one slider per activity: {level 0..1, signals, last_done, last_proposed, last_probe}.
- High slider: exploit. Propose that activity when it's due; yes/no/ignored replies are the feedback.
- Low slider: we'd never get feedback by not proposing, so occasionally *probe* ("would you be into a trip
  this year?") to see if it should be higher. Groups drift, so this never fully stops.
All knobs live in playbook.md so the reflector can tune them.
"""
import json
import re
from datetime import datetime

from social_glue.brain import Brain

ACTIVITIES = ("call", "event", "trip")
DEFAULT_CADENCE = {"call": 7, "event": 14, "trip": 90}
# Big asks start below the probe line, so the bot checks before pushing a trip on anyone.
DEFAULT_PRIOR = {"call": 0.5, "event": 0.4, "trip": 0.2}


def knob(playbook: str, key: str, default: float) -> float:
    m = re.search(rf"{key}:\s*([\d.]+)", playbook)
    return float(m.group(1)) if m else default


def load(brain: Brain) -> dict:
    p = brain.root / "interests.md"
    m = re.search(r"<!-- sliders: (.*?) -->", p.read_text(), re.S) if p.exists() else None
    sliders = json.loads(m.group(1)) if m else {}
    for a in ACTIVITIES:
        prior = knob(brain.playbook, f"prior_interest_{a}", DEFAULT_PRIOR[a])
        sliders.setdefault(a, {"level": prior, "signals": 0, "last_done": None, "last_proposed": None, "last_probe": None})
    return sliders


def save(brain: Brain, sliders: dict) -> None:
    lines = [f"<!-- sliders: {json.dumps(sliders)} -->", "# Group interests", ""]
    for a, s in sliders.items():
        bar = "█" * round(s["level"] * 10) + "░" * (10 - round(s["level"] * 10))
        lines.append(f"- **{a}** {bar} {s['level']:.2f}  ({s['signals']} signals, last done {(s['last_done'] or 'never')[:10]})")
    (brain.root / "interests.md").write_text("\n".join(lines) + "\n")


def update(brain: Brain, activity: str, signal: float, ts: str) -> str:
    """Move a slider toward a signal (1 = yes/enthusiastic, 0 = no, ~0.2 = ignored)."""
    sliders = load(brain)
    s = sliders[activity]
    old = s["level"]
    s["level"] = round(old + knob(brain.playbook, "learning_rate", 0.3) * (signal - old), 3)
    s["signals"] += 1
    save(brain, sliders)
    return f"interest.{activity}: {old:.2f} -> {s['level']:.2f}"


def mark(brain: Brain, activity: str, field: str, ts: str) -> None:
    sliders = load(brain)
    sliders[activity][field] = ts
    save(brain, sliders)


def _days(a: str | None, b: datetime) -> float:
    return 999 if a is None else (b - datetime.fromisoformat(a)).total_seconds() / 86400


def choose(brain: Brain, now: str) -> tuple[str, str] | None:
    """Pick what to do next: ("propose", activity), ("probe", activity), or None.

    Exploit first: the highest slider whose cadence is due. Otherwise explore: the least-known low slider
    that hasn't been probed recently.
    """
    t = datetime.fromisoformat(now)
    pb = brain.playbook
    sliders = load(brain)
    threshold = knob(pb, "probe_below", 0.35)
    due = []
    for a, s in sliders.items():
        cadence = knob(pb, f"cadence_days_{a}", DEFAULT_CADENCE[a])
        if s["level"] >= threshold and _days(s["last_done"], t) >= cadence and _days(s["last_proposed"], t) >= knob(pb, "repropose_after_days", 2):
            due.append((s["level"], -ACTIVITIES.index(a), a))  # ties go to the lighter-weight activity
    if due:
        return "propose", max(due)[2]
    probe_every = knob(pb, "probe_every_days", 7)
    low = [(s["signals"], a) for a, s in sliders.items() if s["level"] < threshold and _days(s["last_probe"], t) >= probe_every]
    if low:
        return "probe", min(low)[1]
    return None


def detect(text: str) -> str | None:
    """Which activity a message is about (used to read feedback and by the sim)."""
    t = text.lower()
    if re.search(r"\btrip\b|weekend away|getaway|travel|cabin", t):
        return "trip"
    if re.search(r"\bcall\b|video|facetime|zoom|catch ?up", t):
        return "call"
    if re.search(r"event|show|concert|market|trivia|gig|festival|exhibit|game night|jazz|music", t):
        return "event"
    return None
