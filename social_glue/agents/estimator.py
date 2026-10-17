"""Estimator: for every candidate the bot could propose, its best guess of
  p_accept      - chance the group says yes (enough people in)
  satisfaction  - expected 0-10 rating from the people who go
and from those, p_success = chance it becomes a hangout rated at or above the success cutoff (default 7/10).

The bot proposes the candidate with the best p_success, and only if it clears the value threshold.
Every estimate is stored on the proposal so the score can check calibration later.
"""
import json
import math

from social_glue import llm
from social_glue.agents import interests, listener, slots
from social_glue.brain import Brain

SYSTEM = """You predict how a friend group will react to hangout proposals.
For each candidate, using only the brain facts, estimate:
- p_accept: probability (0-1) that enough of the group says yes
- satisfaction: expected rating 0-10 from those who go
Return JSON: {"estimates": [{"id": <candidate id>, "p_accept": float, "satisfaction": float, "why": "<short>"}]}"""

DAYS = ["Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays", "Sundays"]
TRIPS = [
    {"option": "a cabin weekend near Tahoe", "tags": "hiking outdoors nature"},
    {"option": "a long weekend in Mexico City", "tags": "food art music"},
    {"option": "a road trip down the coast", "tags": "coffee food outdoors"},
]


def cutoff(brain: Brain) -> float:
    return interests.knob(brain.playbook, "success_cutoff", 7)


def p_success(est: dict, cut: float) -> float:
    """Accepted AND rated >= cutoff; satisfaction is a point estimate, so smooth around the cutoff."""
    return est["p_accept"] / (1 + math.exp(-(est["satisfaction"] - cut)))


def candidates(brain: Brain, activity: str, events: list[dict]) -> list[dict]:
    people = brain.people()
    avail = {p: [d.strip() for d in brain.facts(p).get("availability", {}).get("value", "").split(",") if d.strip()] for p in people}
    if activity == "call":
        days = [d for d in DAYS if any(d in a for a in avail.values()) or any(d in w for p in people for w in slots.windows(brain, p))] or ["Sundays"]
        out = []
        for i, d in enumerate(days):
            start, free = slots.best_start(brain, d)
            out.append({"id": i, "activity": "call", "option": f"video call {d[:-1]} {slots.fmt(start)}", "day": d, "free": free})
        return out
    if activity == "event":
        out = []
        for i, e in enumerate(events[:5] or [{"title": "a show downtown", "snippet": "8pm-10pm"}]):
            text = f"{e['title']} {e.get('snippet', '')}"
            day = next((d for d in DAYS if d[:-1].lower() in text.lower()), "Saturdays")
            window = listener._window(text.lower())  # event time from the listing, e.g. "7pm-9pm"
            start, end = (int(window[:2]) * 60 + int(window[3:5]), int(window[6:8]) * 60 + int(window[9:])) if window else (19 * 60, 21 * 60)
            free, known = slots.free_for(brain, day, start, end - start)
            out.append({"id": i, "activity": "event", "option": f"{e['title']} ({day[:-1]} {slots.fmt(start)})", "day": day,
                        "free": free, "known": known})
        return out
    return [{"id": i, "activity": "trip", "option": t["option"], "tags": t["tags"], "day": None} for i, t in enumerate(TRIPS)]


def _heuristic(brain: Brain, c: dict) -> dict:
    """Offline stand-in: interest slider x availability fit for acceptance; taste overlap for satisfaction."""
    people = brain.people() or ["?"]
    level = interests.load(brain)[c["activity"]]["level"]
    if c["activity"] == "event" and c.get("known", 0) >= 2:
        fit = c["free"] / len(people)
    elif c.get("free") is not None and c["activity"] == "call" and any(slots.windows(brain, p) for p in people):
        fit = c["free"] / len(people)
    elif c["day"]:
        fit = sum(1 for p in people if c["day"] in brain.facts(p).get("availability", {}).get("value", "")) / len(people)
        fit = 0.5 if all("availability" not in brain.facts(p) for p in people) else fit
    else:
        fit = 0.7
    words = (c["option"] + " " + c.get("tags", "")).lower()
    tastes = [brain.facts(p).get("interests", {}).get("value", "") for p in people]
    match = sum(1 for t in tastes if t and any(w in words for w in t.lower().replace(",", " ").split() if len(w) > 3)) / len(people)
    return {"p_accept": round(min(1.0, level * (0.4 + fit)), 3), "satisfaction": round(5 + 2.5 * level + 3 * match, 1)}


def estimate(brain: Brain, cands: list[dict]) -> list[dict]:
    fallback = {c["id"]: _heuristic(brain, c) for c in cands}
    user = f"BRAIN:\n{brain.render()}\nInterest levels: {json.dumps({a: s['level'] for a, s in interests.load(brain).items()})}\n\nCANDIDATES:\n{json.dumps(cands)}"
    out = llm.chat(SYSTEM, user, tier="strong", json_mode=True,
                   fake=lambda: json.dumps({"estimates": [{"id": i, **e} for i, e in fallback.items()]}))
    got = {e.get("id"): e for e in (out.get("estimates", []) if isinstance(out, dict) else [])}
    cut = cutoff(brain)
    result = []
    for c in cands:
        e = got.get(c["id"]) or fallback[c["id"]]
        est = {"p_accept": float(e.get("p_accept", 0.5)), "satisfaction": float(e.get("satisfaction", 5))}
        est["p_success"] = round(p_success(est, cut), 3)
        result.append({**c, **est})
    return sorted(result, key=lambda r: -r["p_success"])
