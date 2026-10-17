"""Tracker: notices when the group agrees to a proposal and records it as a meetup in group.md.

In the sim a confirmed plan counts as a meetup on the day it's confirmed; with real users you'd
confirm after the date passes.
"""
import re

from social_glue.brain import Brain

YES = re.compile(r"works for me|i'm in|im in|count me in|sounds good|let's do it|yes!|down\b", re.I)


def days_since_meetup(brain: Brain, now: str) -> float | None:
    from datetime import datetime

    f = brain.facts("group").get("last_meetup")
    if not f:
        return None
    return (datetime.fromisoformat(now) - datetime.fromisoformat(f["value"])).total_seconds() / 86400


def update(brain: Brain, msg: dict, history: list[dict], accepted: set[str]) -> str | None:
    """Call on every human message. Returns a note when a plan gets confirmed."""
    proposals = [b for b in history if b["kind"] == "propose"]
    if not proposals or not YES.search(msg["text"]):
        return None
    last = proposals[-1]
    group = brain.facts("group")
    if group.get("confirmed_plan", {}).get("ts") == last["ts"]:
        return None  # already confirmed
    accepted.add(msg["name"])
    members = max(len(brain.people()), 1)
    if len(accepted) * 2 <= members:
        return None
    for key, value in (("confirmed_plan", last["text"][:100]), ("last_meetup", msg["ts"])):
        group[key] = {"value": value, "source_msg": msg["text"][:120], "ts": last["ts"] if key == "confirmed_plan" else msg["ts"], "confidence": 1.0}
    brain.write("group", group)
    accepted.clear()
    return f"group.last_meetup -> {msg['ts'][:10]} ({members} members, majority said yes)"
