"""Simulated friends with hidden ground truth. They reveal facts slowly, answer proposals and probes
according to the group's hidden (and drifting) appetite for each activity, and get annoyed by an over-eager bot."""
import json
import random
from datetime import datetime, timedelta

from social_glue import llm
from social_glue.agents.interests import detect

SYSTEM = """You are {name}, texting in your friend group chat. Stay in character, casual, short (under 20 words).
Hidden truth about you (reveal only when asked or when it comes up naturally): free on {availability}; into {interests}; budget ${budget}.
Right now your appetite for hanging out this way is: {appetite}. If the bot (Glue) proposes or asks about one of these,
say yes if your appetite for it is high and it fits you; otherwise decline and say why in your own words
(not into that activity right now / wrong day or too soon / wrong kind of event, place or price). You get irritated when Glue messages out of the blue too much.
Return JSON: {{"text": "<your message>"}}"""


def describe(appetite: dict) -> str:
    word = lambda x: "high" if x >= 0.6 else "medium" if x >= 0.35 else "low"  # noqa: E731
    return ", ".join(f"{a}s: {word(v)}" for a, v in appetite.items())


class Persona:
    def __init__(self, spec: dict, rng: random.Random, appetite: dict):
        self.spec = spec
        self.name = spec["name"]
        self.rng = rng
        self.appetite = appetite  # shared dict owned by the episode, so drift reaches everyone
        self.noise = {a: rng.uniform(-0.15, 0.15) for a in appetite}  # people in a group don't agree exactly
        self.lines = list(spec.get("lines", []))
        self.revealed_availability = any("free" in l.lower() for l in self.lines)

    def wants(self, activity: str) -> float:
        return max(0.0, min(1.0, self.appetite[activity] + self.noise[activity]))

    def reaction(self, chat: list[dict]) -> str:
        """Deterministic so scoring is stable: out-of-the-blue bot messages in the last 7 days vs. this person's threshold."""
        if not chat:
            return "none"
        now = datetime.fromisoformat(chat[-1]["ts"])
        # Replies to someone are fine in a busy week; out-of-the-blue bot messages are what wear people down.
        bot_unprompted = sum(
            1 for i, m in enumerate(chat)
            if m["name"] == "Glue" and now - datetime.fromisoformat(m["ts"]) < timedelta(days=7)
            and not (i and chat[i - 1]["name"] != "Glue" and datetime.fromisoformat(m["ts"]) - datetime.fromisoformat(chat[i - 1]["ts"]) < timedelta(hours=1))
        )
        t = self.spec["annoyance_threshold"]
        return "muted" if bot_unprompted > t + 2 else "annoyed" if bot_unprompted > t else "none"

    def _answer(self, activity: str, text: str) -> str:
        """Yes, or no with a reason: wrong activity, wrong timing, or wrong specifics."""
        t = text.lower()
        if self.rng.random() > self.wants(activity):
            return self.rng.choice([f"nah, not really into {activity}s right now", f"I'll pass, {activity}s aren't my thing lately"])
        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        named = [d for d in days if d.lower() in t]
        if activity != "trip" and named and not any(n + "s" in self.spec["availability"] for n in named):
            return f"can't do {named[0]} though, wrong day for me"
        if activity == "event" and not any(i.split()[0] in t for i in self.spec["interests"]):
            return f"not that kind of thing for me, I'm more into {self.spec['interests'][0]}"
        return self.rng.choice(["I'm in!", "works for me!", "ooh yes, would be into that"])

    def _fake_text(self, chat: list[dict]) -> str:
        idx = next((i for i in range(len(chat) - 1, max(len(chat) - 5, -1), -1) if chat[i]["name"] == "Glue"), None)
        last_bot = chat[idx]["text"] if idx is not None else ""
        already = idx is not None and any(m["name"] == self.name for m in chat[idx + 1:])
        activity = detect(last_bot) if last_bot and "?" in last_bot else None
        if activity and not already:
            return self._answer(activity, last_bot)
        asked = "?" in last_bot and (self.name.lower() in last_bot.lower() or "which" in last_bot.lower())
        if asked and not self.revealed_availability:
            self.revealed_availability = True
            return f"I'm usually free {' and '.join(self.spec['availability'])}"
        if self.lines:
            return self.lines.pop(0)
        return self.rng.choice(["lol", "haha", "same", "😂", "true"])

    def reply(self, chat: list[dict]) -> dict:
        appetite = {a: self.wants(a) for a in self.appetite}
        system = SYSTEM.format(name=self.name, availability=", ".join(self.spec["availability"]),
                               interests=", ".join(self.spec["interests"]), budget=self.spec["budget"], appetite=describe(appetite))
        transcript = "\n".join(f"{m['name']}: {m['text']}" for m in chat[-10:])
        out = llm.chat(system, transcript or "(chat is quiet; say something)", tier="fast", json_mode=True,
                       fake=lambda: json.dumps({"text": self._fake_text(chat)}))
        return {"name": self.name, "text": out.get("text", "lol"), "reaction": self.reaction(chat)}
