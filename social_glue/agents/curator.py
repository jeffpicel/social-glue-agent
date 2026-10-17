"""Curator: the only writer to brain/. Merges patches, resolves conflicts, keeps files lean."""
import json

from social_glue import llm
from social_glue.brain import Brain

MAX_FACTS_PER_PERSON = 8

SYSTEM = """You maintain one friend's profile for a group-chat planning bot.
Given current facts and new patches, return the updated facts as JSON: {"facts": {key: {value, source_msg, ts, confidence}}}.
Rules: newer information wins over older; if a new fact contradicts an old one (e.g. "free Tuesdays" vs "Tuesday class now"),
rewrite the old fact so the profile is consistent and keep the newer source_msg/ts. Merge lists (interests) instead of replacing.
Drop low-value or stale facts so there are at most 8 keys. Keep values short."""


def _split(v: str) -> list[str]:
    return [x.strip() for x in v.split(",") if x.strip()]


def _merge_rules(facts: dict, patches: list[dict], notes: list[str]) -> dict:
    facts = {k: dict(v) for k, v in facts.items()}
    for p in patches:
        new = {k: p[k] for k in ("value", "source_msg", "ts", "confidence")}
        key, old = p["key"], facts.get(p["key"])
        if key == "interests" and old:
            new["value"] = ", ".join(dict.fromkeys(_split(old["value"]) + _split(p["value"])))
        elif key == "free_times" and old:  # new windows replace that day's old ones; other days are kept
            days = {w.split()[0] for w in _split(p["value"])}
            new["value"] = ", ".join([w for w in _split(old["value"]) if w.split()[0] not in days] + _split(p["value"]))
        elif old and old["value"] != new["value"]:
            notes.append(f"{p['who']}.{key}: '{old['value']}' -> '{new['value']}'")
        facts[key] = new
        # Cross-key conflict: a day that's now unavailable can't stay in availability (and vice versa).
        other = {"unavailable": "availability", "availability": "unavailable"}.get(key)
        if other and other in facts:
            remaining = [d for d in _split(facts[other]["value"]) if d not in _split(new["value"])]
            if len(remaining) != len(_split(facts[other]["value"])):
                notes.append(f"{p['who']}.{other}: dropped {set(_split(facts[other]['value'])) - set(remaining)} (\"{new['source_msg']}\")")
                if remaining:
                    facts[other]["value"] = ", ".join(remaining)
                else:
                    del facts[other]
    if len(facts) > MAX_FACTS_PER_PERSON:
        for k in sorted(facts, key=lambda k: (facts[k]["confidence"], facts[k]["ts"]))[: len(facts) - MAX_FACTS_PER_PERSON]:
            notes.append(f"compacted {k}")
            del facts[k]
    return facts


def curate(brain: Brain, patches: list[dict]) -> list[str]:
    """Apply patches to the brain. Returns human-readable notes (conflicts resolved, facts dropped)."""
    notes: list[str] = []
    by_who: dict[str, list[dict]] = {}
    for p in patches:
        by_who.setdefault(p["who"], []).append(p)
    for who, ps in by_who.items():
        current = brain.facts(who)
        expected = _merge_rules(current, ps, notes)
        user = json.dumps({"current": current, "patches": ps})
        out = llm.chat(SYSTEM, user, tier="strong", json_mode=True, fake=lambda: json.dumps({"facts": expected}))
        brain.write(who, out.get("facts") or expected)
    brain.log.extend(notes)
    return notes
