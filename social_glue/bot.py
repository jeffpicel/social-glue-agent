"""Two entry points share one brain:
- Bot.on_message(msg): listener -> curator -> tracker (reads replies to proposals/probes) -> governor -> planner
- Bot.on_tick(now):    tracker (silence = weak no) -> governor.decide_idle (what's due: propose / probe) -> planner
"""
from datetime import datetime

from social_glue.agents import curator, estimator, governor, interests, listener, planner, tracker, values
from social_glue.tools import search_events
from social_glue.brain import Brain


class Bot:
    name = "Glue"

    def __init__(self, brain_dir: str = "brain", use_brain: bool = True):
        self.brain = Brain(brain_dir)
        self.use_brain = use_brain
        self.transcript: list[dict] = []
        self.history: list[dict] = []  # bot's own messages: {ts, kind, activity, prompted, text, voters, closed}
        self.last_notes: list[str] = []
        self.decisions: list[dict] = []  # every timer decision and what blocked it (explains false negatives)

    @property
    def meetups(self) -> list[dict]:
        return [{"activity": b["activity"], "ts": b["ts"]} for b in self.history if b.get("confirmed")]

    def on_message(self, msg: dict) -> str | None:
        self.transcript.append(msg)
        if msg["name"].lower() not in self.brain.people():
            self.brain.write(msg["name"], {})  # every member gets a brain file, even before we know anything
        self.last_notes = curator.curate(self.brain, listener.listen(msg))
        self.last_notes += tracker.on_reply(self.brain, msg, self.history)
        self.last_notes += tracker.on_rating(self.brain, msg, self.history)
        self.last_notes += values.learn(self.brain, msg["text"])
        decision = governor.decide(self.brain, msg, self.history, self.transcript)
        if decision is None:
            return None
        reason, activity = decision
        recent = self.transcript if not self.use_brain else self.transcript[-3:]
        text = planner.plan(self.brain, reason, recent, use_brain=self.use_brain, activity=activity)
        return self._say(text, msg["ts"], reason, activity, prompted=reason == "addressed")

    def on_tick(self, now: str) -> str | None:
        """Called on a clock (e.g. hourly in Discord, nightly in the sim). The bot's only way to start things."""
        self.last_notes = tracker.on_tick(self.brain, now, self.history)
        last = self.transcript[-1]["ts"] if self.transcript else None
        decision = governor.decide_idle(self.brain, now, last, self.history, self.transcript, log=self.decisions)
        if decision is None:
            return None
        reason, activity = decision
        quiet = (datetime.fromisoformat(now) - datetime.fromisoformat(last)).days if last else 0
        recent = self.transcript if not self.use_brain else self.transcript[-3:]
        s = interests.load(self.brain)[activity]
        done = (s["last_done"] or "never")[:10]
        note = f"Chat quiet for {quiet} days. Last {activity} together: {done}. Keep it low-effort to say yes (or no) to."
        best = None
        if reason == "propose":
            penalty = interests.recency_penalty(self.brain, activity, datetime.fromisoformat(now))
            best = self._best_candidate(activity, penalty)
            if best is None and penalty > 0:
                self.decisions[-1]["blocked"] = "recent_meetup"  # nothing good enough to justify meeting again so soon
                return None
            if best is None:
                reason = "probe"  # nothing concrete looks good enough; ask instead of pushing
            else:
                note += f" Propose exactly this: {best['option']}."
                self.last_notes.append(f"estimate: {best['option']} p_accept {best['p_accept']:.2f}, satisfaction {best['satisfaction']:.1f}/10, p_success {best['p_success']:.2f}")
        text = planner.plan(self.brain, reason, recent, use_brain=self.use_brain, note=note, activity=activity)
        if reason in ("propose", "probe"):
            interests.mark(self.brain, activity, "last_proposed" if reason == "propose" else "last_probe", now)
        self._say(text, now, reason, activity, prompted=False)
        if best:
            self.history[-1]["estimate"] = {k: best[k] for k in ("option", "p_accept", "satisfaction", "p_success")}
        return text

    def _best_candidate(self, activity: str, penalty: float = 0.0) -> dict | None:
        """Estimate every candidate for this activity; return the best if its chance of success clears the bar
        (value threshold plus the recency penalty)."""
        events = []
        if activity == "event":
            tastes = ", ".join(self.brain.facts(p)["interests"]["value"] for p in self.brain.people() if "interests" in self.brain.facts(p))
            events = search_events(self.brain.facts("group").get("location", {}).get("value", "San Francisco"), tastes or "hanging out")
        ranked = estimator.estimate(self.brain, estimator.candidates(self.brain, activity, events))
        bar = values.threshold(values.load(self.brain)) + penalty
        return ranked[0] if ranked and ranked[0]["p_success"] >= bar else None

    def _say(self, text: str, ts: str, kind: str, activity: str | None, prompted: bool) -> str:
        self.history.append({"ts": ts, "kind": kind, "activity": activity, "prompted": prompted, "text": text})
        self.transcript.append({"name": self.name, "text": text, "ts": ts})
        return text


if __name__ == "__main__":
    import tempfile

    bot = Bot(tempfile.mkdtemp())
    script = [
        ("Maya", "hey all, I'm free Tuesdays and Thursdays after 6"),
        ("Sam", "I love board games and live music. Tuesdays and Thursdays work for me"),
        ("Priya", "ugh work has been insane. I'm free Tuesdays and Thursdays too"),
        ("Maya", "actually Thursdays are out now, I started a pottery class"),
    ]
    for i, (name, text) in enumerate(script):
        msg = {"name": name, "text": text, "ts": f"2026-10-{12 + i:02d}T18:00:00"}
        print(f"{name}: {text}")
        reply = bot.on_message(msg)
        for n in bot.last_notes:
            print(f"   [brain] {n}")
        if reply:
            print(f"Glue: {reply}")
    for day, replies in [(16, [("Sam", "I'm in"), ("Priya", "works for me!")]), (18, [("Maya", "nah not really for me"), ("Sam", "not really")])]:
        tick = f"2026-10-{day}T21:00:00"
        if (reply := bot.on_tick(tick)):
            print(f"Glue: {reply}")
        for n, t in replies:
            print(f"{n}: {t}")
            bot.on_message({"name": n, "text": t, "ts": f"2026-10-{day}T22:00:00"})
            for note in bot.last_notes:
                print(f"   [brain] {note}")
    print("\n--- brain ---\n" + bot.brain.render())
    print((bot.brain.root / "interests.md").read_text())
