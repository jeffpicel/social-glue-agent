"""Two entry points share one brain:
- Bot.on_message(msg): listener -> curator -> tracker (reads replies to proposals/probes) -> governor -> planner
- Bot.on_tick(now):    tracker (silence = weak no) -> governor.decide_idle (what's due: propose / probe) -> planner
"""
import re
from datetime import datetime

from social_glue import calendar
from social_glue.agents import curator, estimator, governor, interests, listener, planner, tracker, values
from social_glue.tools import search_events
from social_glue.brain import Brain

PLAN_ASK = re.compile(r"\b(plan|propose|suggest|organi[sz]e|set up|schedule|ideas?|hang ?out|get together|meet ?up|something to do|(could|should|can) (we )?do|anything fun|find|look ?up|search|check|google|partiful|luma|eventbrite|listings?|what'?s (on|happening)|recommend\w*|options|picks?)\b", re.I)
WHEN = [(r"\btonight\b|\btoday\b", "today"), (r"\btomorrow\b", "tomorrow"), (r"\bweekend\b", "this weekend"), (r"\bthis week\b|\bsoon\b|\bfast\b", "this week")]
# Words that say how to ask, not what to look for. What's left of an ask is the search topic ("art", "jazz").
FILLER = set("""glue gluebot hey hi yo pls please can could would you u we us me our i find look up search check google partiful luma
eventbrite listing listings get give show suggest propose recommend plan any anything some something cool fun good nice great
fast quick quickly do it a an the to for of in on at this that these next week weekend tonight today tomorrow event events
thing things go out with and or just again what whats happening on there sf city local nearby around options option picks pick
few one two three""".split())


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
        open_items = {id(b) for b in self.history if not b.get("confirmed")}
        self.last_notes += tracker.on_reply(self.brain, msg, self.history)
        just_confirmed = [b for b in self.history if b.get("confirmed") and id(b) in open_items]
        self.last_notes += tracker.on_rating(self.brain, msg, self.history)
        self.last_notes += values.learn(self.brain, msg["text"])
        if just_confirmed:  # a plan just got enough yeses: send the invite instead of more chat
            plan = just_confirmed[-1]
            going = [n for n, yes in plan.get("voters", {}).items() if yes]
            text = calendar.invite({**plan.get("estimate", {}), "option": plan.get("estimate", {}).get("option", plan["text"])}, msg["ts"], going)
            if text:
                return self._say(f"It's on! {text}", msg["ts"], "invite", plan.get("activity"), prompted=True)
        decision = governor.decide(self.brain, msg, self.history, self.transcript)
        if decision is None:
            return None
        reason, activity = decision
        if reason == "ask" and activity is None:
            activity = interests.detect(msg["text"])
            if activity is None:
                sliders = interests.load(self.brain)
                activity = max(sliders, key=lambda a: sliders[a]["level"])
        recent = self.transcript if not self.use_brain else self.transcript[-3:]
        note, best = "", None
        if PLAN_ASK.search(msg["text"]) or reason == "ask":  # the reply governor may label a plan request any reason
            # A direct ask to plan skips the timer and its gates: propose the best option now, whatever the bar.
            sliders = interests.load(self.brain)
            activity = interests.detect(msg["text"]) or activity or max(sliders, key=lambda a: sliders[a]["level"])
            best = self._best_candidate(activity, bar=0.0, ask=msg["text"])
            if best is None and activity == "event":
                note = ("They asked for an event. Your live event search ran but found nothing that fits."
                        " Say that plainly (never claim you can't search) and offer one concrete alternative or ask what to look for.")
            if best:
                reason, note = "propose", f"They asked you to plan something. Propose exactly this: {best['option']}." + self._availability_ask(best)
                interests.mark(self.brain, activity, "last_proposed", msg["ts"])
                self.last_notes.append(f"asked to plan: {best['option']} p_success {best['p_success']:.2f}")
        text = self._with_link(planner.plan(self.brain, reason, recent, use_brain=self.use_brain, note=note, activity=activity), activity, best, reason)
        # A chat-path response is prompted by the incoming message, unlike a timer nudge.
        self._say(text, msg["ts"], reason, activity, prompted=True)
        if best:
            self.history[-1]["estimate"] = self._plan_details(best)
        return text

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
                note += f" Propose exactly this: {best['option']}." + self._availability_ask(best)
                self.last_notes.append(f"estimate: {best['option']} p_accept {best['p_accept']:.2f}, satisfaction {best['satisfaction']:.1f}/10, p_success {best['p_success']:.2f}")
        text = self._with_link(planner.plan(self.brain, reason, recent, use_brain=self.use_brain, note=note, activity=activity), activity, best, reason)
        if reason in ("propose", "probe", "ask"):
            interests.mark(self.brain, activity, "last_probe" if reason == "probe" else "last_proposed", now)
        self._say(text, now, reason, activity, prompted=False)
        if best:
            self.history[-1]["estimate"] = self._plan_details(best)
        return text

    @staticmethod
    def _topic(text: str) -> tuple[str | None, str]:
        """What to search for and when, from a direct ask: "find a cool art event this week" -> ("art", "this week")."""
        t = re.sub(r"<@!?\d+>|https?://\S+", " ", text.lower())
        when = next((w for pat, w in WHEN if re.search(pat, t)), "this month")
        words = [w for w in re.findall(r"[a-z][a-z'-]+", t) if w.replace("'", "") not in FILLER]
        return (" ".join(words) or None), when

    def _best_candidate(self, activity: str, penalty: float = 0.0, bar: float | None = None, ask: str = "") -> dict | None:
        """Estimate every candidate for this activity; return the best if its chance of success clears the bar
        (value threshold plus the recency penalty, unless an explicit bar is given)."""
        events = []
        if activity == "event":
            tastes = ", ".join(self.brain.facts(p)["interests"]["value"] for p in self.brain.people() if "interests" in self.brain.facts(p))
            topic, when = self._topic(ask)
            events = search_events(self.brain.facts("group").get("location", {}).get("value", "San Francisco"), topic or tastes or "hanging out", when)
        cands = estimator.candidates(self.brain, activity, events)
        # Step 2 for events: availability is a given. Drop events we know too few people can make;
        # keep ones we lack data for, and ask about the time when proposing them.
        cands = [c for c in cands if c["activity"] != "event" or c["free"] >= min(2, c["known"])]
        ranked = estimator.estimate(self.brain, cands)
        bar = values.threshold(values.load(self.brain)) + penalty if bar is None else bar
        return ranked[0] if ranked and ranked[0]["p_success"] >= bar else None

    @staticmethod
    def _plan_details(best: dict) -> dict:
        """What we keep about a proposal: the estimate (for calibration) and when/where (for the invite)."""
        return {k: best[k] for k in ("option", "p_accept", "satisfaction", "p_success", "day", "start", "minutes", "url") if k in best}

    @staticmethod
    def _with_link(text: str, activity: str | None, best: dict | None, reason: str = "propose") -> str:
        """Every event proposal carries its link, or says plainly that there isn't one. Other chat is left alone."""
        if reason != "propose" or (activity != "event" and (best or {}).get("activity") != "event"):
            return text
        if re.search(r"https?://", text) or "no link available" in text.lower():
            return text
        url = (best or {}).get("url") if (best or {}).get("activity") == "event" else None
        return f"{text}\n{url}" if url else f"{text}\n(No link available for this one.)"

    @staticmethod
    def _availability_ask(best: dict) -> str:
        out = f" Include this link: {best['url']}." if best.get("url") else ""
        if best["activity"] == "event" and best.get("known", 0) < 2:
            out += " We don't know who's free then, so ask who can make that time."
        return out

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
