"""Governor: decides whether the bot speaks this turn, using playbook.md. Deterministic so it's cheap and testable."""
import re
from datetime import datetime, timedelta

from social_glue.brain import Brain

BOT_NAMES = ("glue", "bot", "@glue")


def budget(playbook: str) -> int:
    m = re.search(r"max_ignored_nudges_per_week:\s*(\d+)", playbook)
    return int(m.group(1)) if m else 3


def ignored_nudges(bot_history: list[dict], transcript: list[dict], now: datetime) -> list[dict]:
    """Unprompted bot messages in the last 7 days that no human answered within a day.

    Only these count against the budget, so a busy planning week where people engage is unlimited,
    while a bot talking to a silent room runs out fast.
    """
    out = []
    for b in bot_history:
        t = datetime.fromisoformat(b["ts"])
        if b["prompted"] or t <= now - timedelta(days=7):
            continue
        answered = any(m["name"] != "Glue" and t < datetime.fromisoformat(m["ts"]) <= t + timedelta(days=1) for m in transcript)
        if not answered and now - t >= timedelta(hours=1):
            out.append(b)
    return out


def quiet_days(playbook: str) -> int:
    m = re.search(r"nudge_after_quiet_days:\s*(\d+)", playbook)
    return int(m.group(1)) if m else 3


def overdue_quiet_days(playbook: str) -> int:
    m = re.search(r"overdue_nudge_after_quiet_days:\s*(\d+)", playbook)
    return int(m.group(1)) if m else 1


def target_days(playbook: str) -> int:
    m = re.search(r"target_meetup_every_days:\s*(\d+)", playbook)
    return int(m.group(1)) if m else 14


def overdue(brain: Brain, now: str) -> float:
    """Days since the last meetup as a fraction of the target cadence. Unknown counts as overdue."""
    from social_glue.agents.tracker import days_since_meetup

    d = days_since_meetup(brain, now)
    return 1.0 if d is None else d / target_days(brain.playbook)


def decide_idle(brain: Brain, now: str, last_activity: str | None, bot_history: list[dict], transcript: list[dict]) -> str | None:
    """Timer path. Driven mainly by time since the last meetup, with chat silence as a secondary signal:
    - met recently (< half the target cadence): stay quiet even if the chat is silent
    - overdue (>= target): speak after overdue_nudge_after_quiet_days of silence (short)
    - in between: speak only after nudge_after_quiet_days of silence
    """
    t = datetime.fromisoformat(now)
    due = overdue(brain, now)
    quiet = (t - datetime.fromisoformat(last_activity)).total_seconds() / 86400 if last_activity else 99
    if due < 0.5:
        return None
    if quiet < (overdue_quiet_days(brain.playbook) if due >= 1 else quiet_days(brain.playbook)):
        return None
    if len(ignored_nudges(bot_history, transcript, t)) >= budget(brain.playbook):
        return None
    people = brain.people()
    if len([p for p in people if "availability" in brain.facts(p)]) >= 2:
        return "propose"
    return "ask" if people else None


def decide(brain: Brain, msg: dict, bot_history: list[dict], transcript: list[dict]) -> str | None:
    """Returns the reason to speak ("addressed", "propose", "ask"), or None to stay quiet.

    bot_history: the bot's own past messages [{ts, kind, prompted}].
    """
    text = msg["text"].lower()
    if any(n in text for n in BOT_NAMES):
        return "addressed"

    now = datetime.fromisoformat(msg["ts"])
    if len(ignored_nudges(bot_history, transcript, now)) >= budget(brain.playbook):
        return None
    week = [b for b in bot_history if not b["prompted"] and datetime.fromisoformat(b["ts"]) > now - timedelta(days=7)]

    people = brain.people()
    with_avail = [p for p in people if "availability" in brain.facts(p)]
    proposed_recently = any(b["kind"] == "propose" for b in week)
    if len(with_avail) >= 2 and not proposed_recently and overdue(brain, msg["ts"]) >= 0.5:
        return "propose"
    asked_recently = any(b["kind"] == "ask" for b in week)
    if people and len(with_avail) < len(people) and not asked_recently:
        return "ask"
    return None
