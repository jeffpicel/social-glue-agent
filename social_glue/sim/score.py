"""score(episode) -> plan_quality, annoyance, cost, score."""
LAMBDA = 0.1


def score(episode: dict) -> dict:
    members = episode["group"]["members"]
    proposals = [m["text"] for m in episode["bot_messages"] if m["kind"] == "propose"]
    plan_quality = 0.0
    if proposals:
        text = proposals[-1].lower()
        named = [d for d in ["Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays", "Sundays"] if d[:-1].lower() in text]
        day = named[0] if named else None
        avail = sum(1 for m in members if day in m["availability"]) / len(members) if day else 0
        interest = sum(1 for m in members if any(i.split()[0] in text for i in m["interests"])) / len(members)
        plan_quality = round(0.7 * avail + 0.3 * interest, 3)
    reactions = [r for r in episode["reactions"]]
    annoyance = sum(1 for r in reactions if r == "annoyed") + 2 * sum(1 for r in reactions if r == "muted")
    usage = episode["usage"]
    cost = round(usage["prompt_tokens"] / max(usage["calls"], 1), 1)
    return {"plan_quality": plan_quality, "annoyance": annoyance, "cost": cost,
            "score": round(plan_quality - LAMBDA * annoyance, 3), "bot_messages": len(episode["bot_messages"]),
            "meetups": episode.get("meetups", 0)}
