"""Tracker: turns replies to the bot's proposals and probes into slider updates, and records meetups.

- yes -> slider up; ignored for a day -> small push down
- no, classified by reason, so each "no" fixes the right thing:
    activity  ("not into trips")       -> slider down
    timing    ("can't do Tuesday")      -> slider mostly kept; availability is fixed by the listener/curator
    specifics ("more into live music")  -> slider mostly kept; tastes are fixed by the listener/curator
- enough yeses (>= 2 and more yes than no) -> confirmed: last_done for that activity, last_meetup in group.md
  (in the sim a confirmed plan counts as having happened; with real users you'd confirm afterwards)
"""
import re
from datetime import datetime, timedelta

from social_glue.agents import interests
from social_glue.brain import Brain

YES = re.compile(r"works for me|i'm in|im in|count me in|sounds good|let's do it|\byes\b|\bdown\b|would be into|love that|ooh", re.I)
NO = re.compile(r"\bnah\b|not really|not for me|pass\b|can't do|cannot|not into|not feeling|skip|more into|too expensive|too soon|wrong day", re.I)
TIMING = re.compile(r"can't do|cannot do|wrong day|that day|too soon|busy then|another day|different day|not free", re.I)
SPECIFICS = re.compile(r"more into|not that kind|not my kind|too expensive|somewhere else|different (place|venue|event)|not my thing|rather do", re.I)
SIGNAL = {"activity": 0.0, "timing": 0.8, "specifics": 0.7}
PLANS = ("propose", "ask")  # an "ask" for call times usually suggests one too, so a yes to it is a plan


def reason(text: str) -> str:
    return "timing" if TIMING.search(text) else "specifics" if SPECIFICS.search(text) else "activity"


def _open_item(history: list[dict]) -> dict | None:
    items = [b for b in history if b["kind"] in ("propose", "probe", "ask") and b.get("activity")]
    return items[-1] if items and not items[-1].get("closed") else None


def on_reply(brain: Brain, msg: dict, history: list[dict]) -> list[str]:
    item = _open_item(history)
    if not item or msg["ts"] <= item["ts"]:
        return []
    return vote(brain, item, msg)


def vote(brain: Brain, item: dict, msg: dict) -> list[str]:
    """Apply one person's yes/no reply to a specific proposal (typed, or a 👍/👎 on that message)."""
    if item.get("closed"):
        return []
    yes, no = bool(YES.search(msg["text"])), bool(NO.search(msg["text"]))
    if not (yes or no) or msg["name"] in item.setdefault("voters", {}):
        return []
    item["voters"][msg["name"]] = yes and not no
    if item["voters"][msg["name"]]:
        notes = [interests.update(brain, item["activity"], 1.0, msg["ts"])]
    else:
        why = reason(msg["text"])
        item.setdefault("reasons", []).append(why)
        notes = [interests.update(brain, item["activity"], SIGNAL[why], msg["ts"]) + f" (no: {why})"]
    members = max(len(brain.people()), 1)
    yeses = sum(item["voters"].values())
    nos = len(item["voters"]) - yeses
    # A plan happens when enough people are in, like a real group: at least 2 and more yes than no.
    if item["kind"] in PLANS and yeses >= 2 and yeses > nos:  # a hangout needs at least two people, however few we know
        item["closed"] = item["confirmed"] = True
        interests.mark(brain, item["activity"], "last_done", msg["ts"])
        g = brain.facts("group")
        g["last_meetup"] = {"value": f"{item['activity']} on {msg['ts'][:10]}", "source_msg": item["text"][:100], "ts": msg["ts"], "confidence": 1.0}
        brain.write("group", g)
        notes.append(f"confirmed {item['activity']} ({yeses}/{members} yes)")
    elif len(item["voters"]) >= members or (item["kind"] == "probe" and len(item["voters"]) * 2 > members):
        item["closed"] = True
    return notes


RATING = re.compile(r"\b(10|[0-9])\s*/\s*10\b")


def on_rating(brain: Brain, msg: dict, history: list[dict]) -> list[str]:
    """'8/10' after a hangout: store it on the most recent confirmed proposal and move the slider toward it."""
    m = RATING.search(msg["text"])
    done = [b for b in history if b.get("confirmed")]
    if not m or not done or msg["name"] in done[-1].setdefault("ratings", {}):
        return []
    item, score = done[-1], int(m.group(1))
    item["ratings"][msg["name"]] = score
    return [interests.update(brain, item["activity"], score / 10, msg["ts"]) + f" (rated {score}/10)"]


def on_tick(brain: Brain, now: str, history: list[dict]) -> list[str]:
    """Silence is feedback too: an open item nobody answered within a day nudges its slider down."""
    item = _open_item(history)
    if not item or item.get("voters") or datetime.fromisoformat(now) - datetime.fromisoformat(item["ts"]) < timedelta(days=1):
        return []
    item["closed"] = True
    return [interests.update(brain, item["activity"], 0.2, now) + " (ignored)"]
