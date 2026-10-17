"""Bot.on_message: listener -> curator -> governor -> planner."""
from social_glue.agents import curator, governor, listener, planner
from social_glue.brain import Brain


class Bot:
    name = "Glue"

    def __init__(self, brain_dir: str = "brain", use_brain: bool = True):
        self.brain = Brain(brain_dir)
        self.use_brain = use_brain
        self.transcript: list[dict] = []
        self.history: list[dict] = []  # bot's own messages: {ts, kind, prompted, text}
        self.last_notes: list[str] = []

    def on_message(self, msg: dict) -> str | None:
        self.transcript.append(msg)
        if msg["name"].lower() not in self.brain.people():
            self.brain.write(msg["name"], {})  # every member gets a brain file, even before we know anything
        self.last_notes = curator.curate(self.brain, listener.listen(msg))
        reason = governor.decide(self.brain, msg, self.history)
        if reason is None:
            return None
        recent = self.transcript if not self.use_brain else self.transcript[-3:]
        text = planner.plan(self.brain, reason, recent, use_brain=self.use_brain)
        kind = "ask" if reason == "addressed" else reason
        self.history.append({"ts": msg["ts"], "kind": kind, "prompted": reason == "addressed", "text": text})
        self.transcript.append({"name": self.name, "text": text, "ts": msg["ts"]})
        return text


if __name__ == "__main__":
    import tempfile

    bot = Bot(tempfile.mkdtemp())
    script = [
        ("Maya", "hey all, I'm free Tuesdays and Thursdays after 6"),
        ("Sam", "I love board games and live music. Thursdays work for me"),
        ("Priya", "ugh work has been insane"),
        ("Maya", "actually Thursdays are out now, I started a pottery class"),
        ("Priya", "glue what are we doing this week?"),
    ]
    for i, (name, text) in enumerate(script):
        msg = {"name": name, "text": text, "ts": f"2026-10-{12 + i:02d}T18:00:00"}
        print(f"{name}: {text}")
        reply = bot.on_message(msg)
        for n in bot.last_notes:
            print(f"   [curator] {n}")
        if reply:
            print(f"Glue: {reply}")
    print("\n--- brain ---\n" + bot.brain.render())
