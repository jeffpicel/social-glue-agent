"""Two entry points share one brain:
- Bot.on_message(msg): listener -> curator -> governor -> planner (reacting to the chat)
- Bot.on_tick(now): governor.decide_idle -> planner (speaking up when a meetup is overdue / the chat is quiet)
"""
from datetime import datetime

from social_glue.agents import curator, governor, listener, planner, tracker
from social_glue.brain import Brain


class Bot:
    name = "Glue"

    def __init__(self, brain_dir: str = "brain", use_brain: bool = True):
        self.brain = Brain(brain_dir)
        self.use_brain = use_brain
        self.transcript: list[dict] = []
        self.history: list[dict] = []  # bot's own messages: {ts, kind, prompted, text}
        self.last_notes: list[str] = []
        self.accepted: set[str] = set()  # who said yes to the latest proposal
        self.meetups = 0

    def on_message(self, msg: dict) -> str | None:
        self.transcript.append(msg)
        if msg["name"].lower() not in self.brain.people():
            self.brain.write(msg["name"], {})  # every member gets a brain file, even before we know anything
        self.last_notes = curator.curate(self.brain, listener.listen(msg))
        if (met := tracker.update(self.brain, msg, self.history, self.accepted)):
            self.meetups += 1
            self.last_notes.append(met)
        reason = governor.decide(self.brain, msg, self.history, self.transcript)
        if reason is None:
            return None
        recent = self.transcript if not self.use_brain else self.transcript[-3:]
        text = planner.plan(self.brain, reason, recent, use_brain=self.use_brain)
        return self._say(text, msg["ts"], "ask" if reason == "addressed" else reason, prompted=reason == "addressed")

    def on_tick(self, now: str) -> str | None:
        """Called on a clock (e.g. every evening). Lets the bot restart a chat that has gone quiet."""
        self.last_notes = []
        last = self.transcript[-1]["ts"] if self.transcript else None
        reason = governor.decide_idle(self.brain, now, last, self.history, self.transcript)
        if reason is None:
            return None
        quiet = (datetime.fromisoformat(now) - datetime.fromisoformat(last)).days if last else 0
        since = tracker.days_since_meetup(self.brain, now)
        met = f"It's been {int(since)} days since the group last met" if since is not None else "We don't know when the group last met"
        target = governor.target_days(self.brain.playbook)
        recent = self.transcript if not self.use_brain else self.transcript[-3:]
        note = (f"{met} (target: every {target} days). The chat has been quiet for {quiet} days. "
                "Restart it with something concrete and low-effort to say yes to.")
        text = planner.plan(self.brain, reason, recent, use_brain=self.use_brain, note=note)
        return self._say(text, now, reason, prompted=False)

    def _say(self, text: str, ts: str, kind: str, prompted: bool) -> str:
        self.history.append({"ts": ts, "kind": kind, "prompted": prompted, "text": text})
        self.transcript.append({"name": self.name, "text": text, "ts": ts})
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
        msg = {"name": name, "text": text, "ts": f"2026-10-{12 + i:02d}T18:00:00"}  # last msg on the 16th
        print(f"{name}: {text}")
        reply = bot.on_message(msg)
        for n in bot.last_notes:
            print(f"   [curator] {n}")
        if reply:
            print(f"Glue: {reply}")
    quiet = "2026-10-20T19:00:00"
    print(f"... (4 quiet days, tick at {quiet})")
    if (reply := bot.on_tick(quiet)):
        print(f"Glue: {reply}")
    print("\n--- brain ---\n" + bot.brain.render())
