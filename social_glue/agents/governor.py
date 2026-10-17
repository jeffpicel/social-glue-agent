"""Governor: decides whether the bot speaks, and about what. Deterministic so it's cheap and testable.

- Chat path (decide): answer when addressed; otherwise only fill gaps (ask for availability).
- Timer path (decide_idle): initiate. interests.choose() says what's due (propose a wanted activity,
  or probe a low one); the governor checks silence and the ignored-nudge budget.
"""
import re
from datetime import datetime, timedelta

from social_glue.agents import interests
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


def decide_idle(brain: Brain, now: str, last_activity: str | None, bot_history: list[dict], transcript: list[dict],
                log: list | None = None) -> tuple[str, str | None] | None:
    """Returns (reason, activity) or None. Proposals wait for a short lull; probes wait longer.

    If `log` is given, appends {ts, choice, blocked, levels} so the scorer can explain false negatives.
    """
    t = datetime.fromisoformat(now)
    choice = interests.choose(brain, now)
    entry = {"ts": now, "choice": choice, "blocked": None, "levels": {a: s["level"] for a, s in interests.load(brain).items()}}
    if log is not None:
        log.append(entry)
    if choice is None:
        return None
    reason, activity = choice
    quiet = (t - datetime.fromisoformat(last_activity)).total_seconds() / 86400 if last_activity else 99
    wait = interests.knob(brain.playbook, "propose_after_quiet_days" if reason == "propose" else "probe_after_quiet_days", 1 if reason == "propose" else 2)
    if quiet < wait:
        entry["blocked"] = "waiting_for_quiet"
        return None
    if len(ignored_nudges(bot_history, transcript, t)) >= budget(brain.playbook):
        entry["blocked"] = "nudge_budget"
        return None
    if reason == "propose" and activity == "call" and len([p for p in brain.people() if "availability" in brain.facts(p)]) < 2:
        entry["blocked"] = "no_availability"
        return "ask", "call"  # can't pick a call time yet
    return reason, activity


def decide(brain: Brain, msg: dict, bot_history: list[dict], transcript: list[dict]) -> tuple[str, str | None] | None:
    if any(n in msg["text"].lower() for n in BOT_NAMES):
        return "addressed", None
    now = datetime.fromisoformat(msg["ts"])
    if len(ignored_nudges(bot_history, transcript, now)) >= budget(brain.playbook):
        return None
    week = [b for b in bot_history if not b["prompted"] and datetime.fromisoformat(b["ts"]) > now - timedelta(days=7)]
    people = brain.people()
    missing = [p for p in people if "availability" not in brain.facts(p)]
    if len(people) >= 2 and len(missing) * 2 > len(people) and not any(b["kind"] == "ask" for b in week):
        return "ask", None
    return None
