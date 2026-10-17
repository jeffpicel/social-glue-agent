"""Planner: writes the bot's message from the brain only (never the full transcript)."""
from social_glue import llm
from social_glue.brain import Brain
from social_glue.tools import search_events

SYSTEM = """You are Glue, a friendly bot in a friends' group chat that helps them actually hang out.
Follow the playbook exactly. Use only the brain facts given; don't invent facts about people.
Reason for speaking: {reason}.
- propose: suggest ONE concrete plan (day + time + activity) that fits everyone's availability and interests; mention an event if one fits.
- ask: ask ONE short question that fills the biggest gap in the brain (batch several people if useful).
- addressed: answer what was asked, briefly.
Reply with just the chat message."""


def _common_days(brain: Brain) -> list[str]:
    sets = [set(x.strip() for x in brain.facts(p)["availability"]["value"].split(",")) for p in brain.people() if "availability" in brain.facts(p)]
    return sorted(set.intersection(*sets)) if sets else []


def _last_day_mentioned(recent: list[dict]) -> list[str]:
    for m in reversed(recent):
        for d in ["Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays", "Sundays"]:
            if d[:-1].lower() in m["text"].lower():
                return [d]
    return []


def _fake(brain: Brain, reason: str, events: list[dict], recent: list[dict], use_brain: bool) -> str:
    if reason == "propose":
        # Without the brain, the offline stand-in just grabs the last day anyone mentioned.
        days = _common_days(brain) if use_brain else _last_day_mentioned(recent)
        if not days:
            return "No single day works for everyone yet. Anyone flexible on Tuesdays or Thursdays?"
        day = days[0][:-1]
        ev = f" Maybe: {events[0]['title']}?" if events else ""
        return f"Looks like {day} works for everyone who's shared. Call at 7pm this {day}?{ev}"
    missing = [p.capitalize() for p in brain.people() if "availability" not in brain.facts(p)]
    if reason == "ask" and missing:
        return f"Quick one {', '.join(missing)}: which evenings usually work for you?"
    return "On it! Tell me which days work and I'll find a time."


def plan(brain: Brain, reason: str, recent: list[dict], use_brain: bool = True, note: str = "") -> str:
    events = []
    if reason == "propose":
        interests = ", ".join(brain.facts(p)["interests"]["value"] for p in brain.people() if "interests" in brain.facts(p))
        events = search_events(brain.facts("group").get("location", {}).get("value", "San Francisco"), interests or "hanging out")[:3]
    context = brain.render() if use_brain else "\n".join(f"{m['name']}: {m['text']}" for m in recent)
    user = (
        f"PLAYBOOK:\n{brain.playbook}\n\n"
        f"{'BRAIN' if use_brain else 'FULL TRANSCRIPT'}:\n{context}\n\n"
        f"EVENTS:\n" + "\n".join(f"- {e['title']}: {e['snippet']}" for e in events) + "\n\n"
        f"LAST MESSAGES:\n" + "\n".join(f"{m['name']}: {m['text']}" for m in recent[-3:])
        + (f"\n\nNOTE: {note}" if note else "")
    )
    return llm.chat(SYSTEM.format(reason=reason), user, tier="strong", fake=lambda: _fake(brain, reason, events, recent, use_brain))
