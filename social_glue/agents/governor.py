"""Governor: makes a reply-or-silence decision for every human message, plus timer nudges.

- Chat path (decide): use the model to decide whether this message merits a response.
- Timer path (decide_idle): initiate. interests.choose() says what's due (propose a wanted activity,
  or probe a low one); the governor checks silence and the ignored-nudge budget.
"""
import json
import re
from datetime import datetime, timedelta

from social_glue import llm
from social_glue.agents import interests
from social_glue.brain import Brain

BOT_NAMES = ("glue", "bot", "@glue")

REPLY_SYSTEM = """You are the governor for Glue, a helpful friend-group chat bot.
For EVERY incoming human message, decide if Glue should reply now. Most routine statements,
banter, and facts being recorded should get no reply. Reply when someone asks Glue/a useful
group question, addresses Glue, shares something that merits a brief empathetic/social response,
or a short acknowledgement materially helps planning. Do not repeat information already handled.
Never answer messages from Glue (they are excluded before this call).
Return only JSON: {\"reply\": true|false, \"reason\": \"addressed|respond|ask\", \"activity\": \"call|event|trip|null\"}.
Use addressed for direct mentions, respond for a conversational answer, and ask when the human is
asking Glue for an activity idea or recommendation. In that case Glue should suggest something,
not ask the human to provide suggestions. If silence is better, return {\"reply\": false}."""


def _fake_reply_decision(msg: dict) -> str:
    text = msg["text"].lower()
    if any(n in text for n in BOT_NAMES):
        return json.dumps({"reply": True, "reason": "addressed", "activity": None})
    if re.search(r"\b(what should we do|any ideas|any suggestions|what do you recommend|where should we go|suggest something)\b", text):
        return json.dumps({"reply": True, "reason": "ask", "activity": interests.detect(text)})
    if "?" in text:
        return json.dumps({"reply": True, "reason": "respond", "activity": None})
    if re.search(r"\b(congrats|congratulations|sorry to hear|that sucks|thank you|thanks glue)\b", text):
        return json.dumps({"reply": True, "reason": "respond", "activity": None})
    return json.dumps({"reply": False})


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
    # Even with incomplete availability, make a concrete low-commitment suggestion.
    # The planner can use a reasonable default time and invite a yes/no or a constraint.
    return reason, activity


def decide(brain: Brain, msg: dict, bot_history: list[dict], transcript: list[dict]) -> tuple[str, str | None] | None:
    now = datetime.fromisoformat(msg["ts"])
    context = brain.render()
    recent = transcript[-6:]
    user = (f"BRAIN:\n{context}\n\nRECENT CHAT:\n" +
            "\n".join(f"{m['name']}: {m['text']}" for m in recent) +
            f"\n\nINCOMING MESSAGE from {msg['name']}:\n{msg['text']}")
    out = llm.chat(REPLY_SYSTEM, user, tier="fast", json_mode=True,
                   fake=lambda: _fake_reply_decision(msg))
    if not isinstance(out, dict) or not out.get("reply"):
        return None

    reason = out.get("reason")
    if reason not in ("addressed", "respond", "ask"):
        reason = "respond"
    # Addressed responses are always allowed; the nudge budget is for timer-initiated proposals.
    # Every chat-path reply responds to a live message and is therefore marked prompted by Bot.
    activity = out.get("activity")
    if activity not in ("call", "event", "trip"):
        activity = None
    return reason, activity
