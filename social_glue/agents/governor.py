"""Governor: decides whether the bot speaks this turn, using playbook.md. Deterministic so it's cheap and testable."""
import re
from datetime import datetime, timedelta

from social_glue.brain import Brain

BOT_NAMES = ("glue", "bot", "@glue")


def budget(playbook: str) -> int:
    m = re.search(r"max_unprompted_per_week:\s*(\d+)", playbook)
    return int(m.group(1)) if m else 3


def decide(brain: Brain, msg: dict, bot_history: list[dict]) -> str | None:
    """Returns the reason to speak ("addressed", "propose", "ask"), or None to stay quiet.

    bot_history: the bot's own past messages [{ts, kind, prompted}].
    """
    text = msg["text"].lower()
    if any(n in text for n in BOT_NAMES):
        return "addressed"

    now = datetime.fromisoformat(msg["ts"])
    week = [b for b in bot_history if not b["prompted"] and datetime.fromisoformat(b["ts"]) > now - timedelta(days=7)]
    if len(week) >= budget(brain.playbook):
        return None

    people = brain.people()
    with_avail = [p for p in people if "availability" in brain.facts(p)]
    proposed_recently = any(b["kind"] == "propose" for b in week)
    if len(with_avail) >= 2 and not proposed_recently:
        return "propose"
    asked_recently = any(b["kind"] == "ask" for b in week)
    if people and len(with_avail) < len(people) and not asked_recently:
        return "ask"
    return None
