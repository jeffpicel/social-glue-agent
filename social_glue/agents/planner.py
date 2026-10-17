"""Planner: writes the bot's message from the brain (plus the last few messages), not the full transcript."""
from social_glue import llm
from social_glue.agents import interests
from social_glue.brain import Brain
from social_glue.tools import search_events

SYSTEM = """You are Glue, a friendly bot in a friends' group chat that helps them actually hang out.
Follow the playbook. Use only the brain facts given; don't invent facts about people.
Reason for speaking: {reason}. Activity: {activity}.
- propose: suggest ONE concrete {activity} plan (day + time, and place/event/destination) that fits availability and interests. Ask who's in.
- probe: the group hasn't shown interest in {activity} lately. Ask ONE light, no-pressure question to check if they'd want it. Don't propose specifics.
- ask: ask ONE short question that fills the biggest gap in the brain (batch several people).
- addressed: answer what was asked, briefly.
Reply with just the chat message."""

PROBE = {
    "call": "Random q: would a regular video call be nice, like every week or two? Totally fine if not.",
    "event": "Would you all be into going to a show or local event together sometime? No pressure.",
    "trip": "Wild idea: would anyone be into a group trip together this year? Totally fine if not.",
}


def _common_days(brain: Brain) -> list[str]:
    sets = [set(x.strip() for x in brain.facts(p)["availability"]["value"].split(",")) for p in brain.people() if "availability" in brain.facts(p)]
    return sorted(set.intersection(*sets)) if sets else []


def _last_day_mentioned(recent: list[dict]) -> list[str]:
    for m in reversed(recent):
        for d in ["Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays", "Sundays"]:
            if d[:-1].lower() in m["text"].lower():
                return [d]
    return []


def _fake(brain: Brain, reason: str, activity: str | None, events: list[dict], recent: list[dict], use_brain: bool) -> str:
    if reason == "probe":
        return PROBE[activity]
    if reason == "propose":
        # Without the brain, the offline stand-in just grabs the last day anyone mentioned.
        days = _common_days(brain) if use_brain else _last_day_mentioned(recent)
        day = days[0][:-1] if days else "Saturday"
        if activity == "trip":
            return "Long weekend getaway trip next month? Thinking a cabin near Tahoe, split costs. Who's in?"
        if activity == "event":
            ev = events[0]["title"] if events else "a show downtown"
            return f"Event idea: {ev} this {day}. Who's in?"
        if not days:
            return "No single day works for everyone yet for a call. Anyone flexible on Tuesdays or Thursdays?"
        return f"Video call at 7pm this {day}? Looks like it works for everyone who's shared. Who's in?"
    missing = [p.capitalize() for p in brain.people() if "availability" not in brain.facts(p)]
    if reason == "ask" and missing:
        return f"Quick one {', '.join(missing)}: which evenings usually work for you?"
    return "On it! Tell me which days work and I'll find a time."


def plan(brain: Brain, reason: str, recent: list[dict], use_brain: bool = True, note: str = "", activity: str | None = None) -> str:
    events = []
    if reason == "propose" and activity == "event":
        tastes = ", ".join(brain.facts(p)["interests"]["value"] for p in brain.people() if "interests" in brain.facts(p))
        events = search_events(brain.facts("group").get("location", {}).get("value", "San Francisco"), tastes or "hanging out")[:3]
    sliders = interests.load(brain)
    context = brain.render() if use_brain else "\n".join(f"{m['name']}: {m['text']}" for m in recent)
    user = (
        f"PLAYBOOK:\n{brain.playbook}\n\n"
        f"{'BRAIN' if use_brain else 'FULL TRANSCRIPT'}:\n{context}\n"
        f"Group interest levels: " + ", ".join(f"{a} {s['level']:.2f}" for a, s in sliders.items()) + "\n\n"
        f"EVENTS:\n" + "\n".join(f"- {e['title']}: {e['snippet']}" for e in events) + "\n\n"
        f"LAST MESSAGES:\n" + "\n".join(f"{m['name']}: {m['text']}" for m in recent[-3:])
        + (f"\n\nNOTE: {note}" if note else "")
    )
    return llm.chat(SYSTEM.format(reason=reason, activity=activity or "any"), user, tier="strong",
                    fake=lambda: _fake(brain, reason, activity, events, recent, use_brain))
