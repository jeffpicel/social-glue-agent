"""Listener: one chat message -> proposed brain patches. Cheap model; never writes the brain itself."""
import json
import re

from social_glue import llm

KEYS = "availability (days they're free, e.g. 'Tuesdays, Thursdays'), free_times (weekly windows in 24h time rounded to 15 minutes, e.g. 'Tuesdays 18:00-21:00, Saturdays 10:00-12:30'; give both availability and free_times when a time is said), unavailable (days/times they can't do), interests, budget, location, travel (willingness to travel)"

SYSTEM = f"""You extract durable facts about friends from one group-chat message.
Only extract facts useful for planning hangouts. Allowed keys: {KEYS}.
Return JSON: {{"patches": [{{"who": "<name or group>", "key": "<key>", "value": "<short value>", "confidence": 0.0-1.0}}]}}.
Return {{"patches": []}} if the message has nothing durable."""

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _hm(h: str, m: str | None, ap: str | None, evening: bool) -> int:
    h = int(h) % 12 + (12 if ap == "pm" or (ap is None and evening) else 0)
    return h * 60 + (int(m) if m else 0)


def _window(text: str) -> str | None:
    """Offline stand-in for times: "after 6", "6-9pm", "from 7:30", "8:15 to 10" -> "HH:MM-HH:MM" (15-minute steps)."""
    t = r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?"
    if m := re.search(rf"{t}\s*(?:-|to|until)\s*{t}", text):
        evening = "am" not in m.groups()
        a, b = _hm(*m.groups()[:3], evening), _hm(*m.groups()[3:], evening)
    elif m := re.search(rf"(?:after|from|at|around)\s+{t}", text):
        a = _hm(*m.groups(), "am" not in m.groups())
        b = min(a + 180, 23 * 60 + 45)
    else:
        return None
    a, b = a - a % 15, b - b % 15
    return f"{a // 60:02d}:{a % 60:02d}-{b // 60:02d}:{b % 60:02d}" if b > a else None


def _fake(msg: dict) -> str:
    text = msg["text"].lower()
    who = msg["name"]
    patches = []
    days = [d.capitalize() + "s" for d in DAYS if d in text or d + "s" in text]
    if days:
        negative = re.search(r"can't|cannot|out|busy|class|work late|no longer", text)
        key = "unavailable" if negative else "availability"
        patches.append({"who": who, "key": key, "value": ", ".join(days), "confidence": 0.8})
        window = _window(text)
        if window and key == "availability":
            patches.append({"who": who, "key": "free_times", "value": ", ".join(f"{d} {window}" for d in days), "confidence": 0.7})
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
