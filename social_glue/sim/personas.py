"""Simulated friends with hidden ground truth. They reveal facts slowly and get annoyed by an over-eager bot."""
import json
import random

from social_glue import llm

SYSTEM = """You are {name}, texting in your friend group chat. Stay in character, casual, short (under 20 words).
Hidden truth about you (reveal only when asked or when it comes up naturally): free on {availability}; into {interests}; budget ${budget}.
If the bot (Glue) asks you something, answer honestly. You get irritated when Glue messages too much.
Return JSON: {{"text": "<your message>"}}"""


class Persona:
    def __init__(self, spec: dict, rng: random.Random):
        self.spec = spec
        self.name = spec["name"]
        self.rng = rng
        self.lines = list(spec.get("lines", []))
        self.revealed_availability = any("free" in l.lower() for l in self.lines)

    def reaction(self, chat: list[dict]) -> str:
        """Deterministic so scoring is stable: annoyed past the threshold, muted well past it."""
        recent = chat[-12:]
        bot_unprompted = sum(1 for m in recent if m["name"] == "Glue")
        t = self.spec["annoyance_threshold"]
        return "muted" if bot_unprompted > t + 2 else "annoyed" if bot_unprompted > t else "none"

    def _fake_text(self, chat: list[dict]) -> str:
        last_bot = next((m["text"] for m in reversed(chat[-4:]) if m["name"] == "Glue"), "")
        asked = "?" in last_bot and (self.name.lower() in last_bot.lower() or "everyone" in last_bot.lower() or "which" in last_bot.lower())
        if asked and not self.revealed_availability:
            self.revealed_availability = True
            return f"I'm usually free {' and '.join(self.spec['availability'])}"
        if last_bot and "?" in last_bot and self.rng.random() < 0.5:
            days = self.spec["availability"]
            day = next((d for d in days if d[:-1].lower() in last_bot.lower()), None)
            return "works for me!" if day else "can't do that day sorry"
        if self.lines:
            return self.lines.pop(0)
        return self.rng.choice(["lol", "haha", "same", "😂", "true"])

    def reply(self, chat: list[dict]) -> dict:
        system = SYSTEM.format(name=self.name, availability=", ".join(self.spec["availability"]),
                               interests=", ".join(self.spec["interests"]), budget=self.spec["budget"])
        transcript = "\n".join(f"{m['name']}: {m['text']}" for m in chat[-10:])
        out = llm.chat(system, transcript or "(chat is quiet; say something)", tier="fast", json_mode=True,
                       fake=lambda: json.dumps({"text": self._fake_text(chat)}))
        return {"name": self.name, "text": out.get("text", "lol"), "reaction": self.reaction(chat)}
