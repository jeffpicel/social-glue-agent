"""Planner: writes the bot's message from the brain (plus the last few messages), not the full transcript."""
from social_glue import llm
from social_glue.agents import interests
from social_glue.brain import Brain
from social_glue.tools import search_events, search_yelp_places

SYSTEM = """You are Glue, a friendly bot in a friends' group chat that helps them actually hang out.
Follow the playbook. Use only the brain facts given; don't invent facts about people.
Reason for speaking: {reason}. Activity: {activity}.
- propose: suggest ONE concrete {activity} plan (day + time, and place/event/destination) that fits availability and interests. If availability is missing, choose a reasonable low-commitment default and ask who's in; don't ask the group to invent the plan.
- probe: the group hasn't shown interest in {activity} lately. Ask ONE light, no-pressure question to check if they'd want it. Don't propose specifics.
- ask: make a concrete, low-effort recommendation based on the brain, then ask whether people are interested. Don't ask the group for ideas or suggestions. Ask for a missing constraint only if it is essential to choosing safely.
- addressed: answer what was asked, briefly.
- respond: answer the incoming message or react naturally and briefly. Stay relevant to what they said; don't turn ordinary chat into a planning pitch.
When you propose an event that has a link, include the link.
When Yelp venue candidates are provided, use one as a concrete place suggestion when it fits; include its Yelp link. Treat rating, price, category, and address as factual details, and do not invent opening hours or availability.
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


def _fake(brain: Brain, reason: str, activity: str | None, events: list[dict], venues: list[dict], recent: list[dict], use_brain: bool, note: str = "") -> str:
    if reason == "respond":
        incoming = recent[-1] if recent else {"text": ""}
        text = incoming["text"].strip()
        if "?" in text:
            return "Good question! What do you all think?"
        if any(x in text.lower() for x in ("congrats", "congratulations")):
            return "That’s great—congratulations!"
        if any(x in text.lower() for x in ("sorry to hear", "that sucks")):
            return "Ah, sorry—that sounds rough. Hope things get easier."
        return "Got it, thanks for sharing!"
    if reason == "ask":
        if activity == "trip":
            return "How about a long weekend cabin trip near Tahoe sometime this fall? Who'd be interested?"
        if activity == "event":
            event = events[0]["title"] if events else "a local live music night"
            venue = f" at {venues[0]['title']} ({venues[0]['url']})" if venues else ""
            return f"How about checking out {event}{venue} together? Who'd be up for it?"
        return "How about a relaxed 30-minute video call Sunday at 7pm? Who's in?"
    if reason == "probe":
        return PROBE[activity]
    if reason == "propose" and "Propose exactly this: " in note:
        option = note.split("Propose exactly this: ")[1].split(". ")[0].rstrip(".")
        if "ask who can make" in note:
            return f"How about {option}? Who can make that time?"
        return f"How about {option}? Who's in?"
    if reason == "propose":
        # Without the brain, the offline stand-in just grabs the last day anyone mentioned.
        days = _common_days(brain) if use_brain else _last_day_mentioned(recent)
        day = days[0][:-1] if days else "Saturday"
        if activity == "trip":
            return "Long weekend getaway trip next month? Thinking a cabin near Tahoe, split costs. Who's in?"
        if activity == "event":
            ev = events[0]["title"] if events else "a show downtown"
            venue = f" at {venues[0]['title']} ({venues[0]['url']})" if venues else ""
            return f"Event idea: {ev}{venue} this {day}. Who's in?"
        if not days:
            return "How about a relaxed 30-minute video call Sunday at 7pm as a starting point? Who's in?"
        return f"Video call at 7pm this {day}? Looks like it works for everyone who's shared. Who's in?"
    if reason == "ask":
        return "How about a relaxed 30-minute video call Sunday at 7pm? Who's in?"
    return "On it! Tell me which days work and I'll find a time."


def plan(brain: Brain, reason: str, recent: list[dict], use_brain: bool = True, note: str = "", activity: str | None = None) -> str:
    events = []
    venues = []
    if reason in ("propose", "ask") and activity == "event":
        tastes = ", ".join(brain.facts(p)["interests"]["value"] for p in brain.people() if "interests" in brain.facts(p))
        events = search_events(brain.facts("group").get("location", {}).get("value", "San Francisco"), tastes or "hanging out")[:3]
        try:
            venues = search_yelp_places(
                brain.facts("group").get("location", {}).get("value", "San Francisco"),
                f"{tastes} event venue" if tastes else "live music events and venues",
                limit=5,
            )
        except Exception as exc:  # noqa: BLE001 - Yelp is an optional source
            print(f"[yelp] venue search failed: {type(exc).__name__}")
    sliders = interests.load(brain)
    context = brain.render() if use_brain else "\n".join(f"{m['name']}: {m['text']}" for m in recent)
    user = (
        f"PLAYBOOK:\n{brain.playbook}\n\n"
        f"{'BRAIN' if use_brain else 'FULL TRANSCRIPT'}:\n{context}\n"
        f"Group interest levels: " + ", ".join(f"{a} {s['level']:.2f}" for a, s in sliders.items()) + "\n\n"
        f"EVENTS:\n" + "\n".join(f"- {e['title']}: {e['snippet']} {e.get('url', '')}".rstrip() for e in events) + "\n\n"
        f"LOCAL VENUES FROM YELP:\n" + "\n".join(f"- {v['title']}: {v['snippet']} {v['url']}".rstrip() for v in venues) + "\n\n"
        f"LAST MESSAGES:\n" + "\n".join(f"{m['name']}: {m['text']}" for m in recent[-3:])
        + (f"\n\nNOTE: {note}" if note else "")
    )
    return llm.chat(SYSTEM.format(reason=reason, activity=activity or "any"), user, tier="strong",
                    fake=lambda: _fake(brain, reason, activity, events, venues, recent, use_brain, note))
