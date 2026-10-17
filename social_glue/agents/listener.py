"""Listener: one chat message -> proposed brain patches. Cheap model; never writes the brain itself."""
import json
import re

from social_glue import llm

KEYS = "availability (days/times they're free), unavailable (days/times they can't do), interests, budget, location, travel (willingness to travel)"

SYSTEM = f"""You extract durable facts about friends from one group-chat message.
Only extract facts useful for planning hangouts. Allowed keys: {KEYS}.
Return JSON: {{"patches": [{{"who": "<name or group>", "key": "<key>", "value": "<short value>", "confidence": 0.0-1.0}}]}}.
Return {{"patches": []}} if the message has nothing durable."""

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _fake(msg: dict) -> str:
    text = msg["text"].lower()
    who = msg["name"]
    patches = []
    days = [d.capitalize() + "s" for d in DAYS if d in text or d + "s" in text]
    if days:
        negative = re.search(r"can't|cannot|out|busy|class|work late|no longer", text)
        key = "unavailable" if negative else "availability"
        patches.append({"who": who, "key": key, "value": ", ".join(days), "confidence": 0.8})
    m = re.search(r"(?:love|like|into|obsessed with) ([a-z ,&'-]+)", text)
    if m:
        patches.append({"who": who, "key": "interests", "value": m.group(1).strip(" ,"), "confidence": 0.7})
    m = re.search(r"\$(\d+)", text)
    if m:
        patches.append({"who": who, "key": "budget", "value": f"up to ${m.group(1)}", "confidence": 0.7})
    return json.dumps({"patches": patches})


def listen(msg: dict) -> list[dict]:
    user = f"Sender: {msg['name']}\nMessage: {msg['text']}"
    out = llm.chat(SYSTEM, user, tier="fast", json_mode=True, fake=lambda: _fake(msg))
    patches = out.get("patches", []) if isinstance(out, dict) else []
    for p in patches:
        p.setdefault("who", msg["name"])
        p["source_msg"] = msg["text"][:120]
        p["ts"] = msg["ts"]
    return patches
