"""Run one simulated episode: personas <-> bot in a group chat over ~2 weeks.

python -m social_glue.sim.run --group train_1            # live chat, writes ./brain
python -m social_glue.sim.run --group heldout_1 --no-brain
"""
import argparse
import json
import random
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from social_glue import llm
from social_glue.bot import Bot
from social_glue.sim.personas import Persona
from social_glue.sim.score import score

GROUPS = Path(__file__).parent / "groups"

try:
    from rich.console import Console

    console = Console()
    COLORS = ["cyan", "magenta", "yellow", "green", "blue"]

    def show(name, text, color):
        console.print(f"[bold {color}]{name}[/]: {text}")

    def note(text):
        console.print(f"   [dim]{text}[/]")
except ImportError:
    COLORS = [""] * 5

    def show(name, text, color):
        print(f"{name}: {text}")

    def note(text):
        print(f"   {text}")


def load_group(gid: str) -> dict:
    return json.loads((GROUPS / f"{gid}.json").read_text())


def run_episode(group: dict, brain_dir: str | None = None, playbook: str | None = None, use_brain: bool = True,
                days: int = 14, seed: int = 0, verbose: bool = True) -> dict:
    rng = random.Random(seed)
    llm.USAGE.update(calls=0, prompt_tokens=0)
    bot = Bot(brain_dir or tempfile.mkdtemp(), use_brain=use_brain)
    bot.brain.reset()
    if playbook:
        bot.brain.playbook = playbook
    start = datetime(2026, 10, 1, 18)
    bot.brain.write("group", {"location": {"value": group["city"], "source_msg": "setup", "ts": start.isoformat(), "confidence": 1.0}})
    appetite = dict(group["appetite"])  # shared by all personas; drift mutates it mid-episode
    personas = [Persona(m, rng, appetite) for m in group["members"]]
    color = {p.name: COLORS[i % len(COLORS)] for i, p in enumerate(personas)}
    chat = []
    rated = 0
    for day in range(days):
        for a, (when, level) in group.get("drift", {}).items():
            if day == when:
                appetite[a] = level
                if verbose:
                    note(f"[hidden] group appetite for {a}s is now {level}")
        # The day after a hangout someone says how it went; groups that value hangouts more say so.
        if len(bot.meetups) > rated:
            rated = len(bot.meetups)
            p = rng.choice(personas)
            text = "that was so fun, we should do it more" if group.get("values", {}).get("tp", 1.0) >= 1.0 else "it was ok"
            msg = {"name": p.name, "text": text, "ts": (start + timedelta(days=day, minutes=30)).isoformat()}
            chat.append(msg)
            if verbose:
                show(p.name, text, color[p.name])
            bot.on_message(msg)
            if verbose:
                for n in bot.last_notes:
                    note(f"[brain] {n}")
        quiet = rng.random() < 0.4  # some days nobody talks; the bot's timer path has to notice
        for turn in range(0 if quiet else 2):
            p = rng.choice(personas)
            msg = p.reply(chat)
            msg["ts"] = (start + timedelta(days=day, hours=turn)).isoformat()
            chat.append(msg)
            if verbose:
                show(p.name, msg["text"], color[p.name])
            text = bot.on_message({k: msg[k] for k in ("name", "text", "ts")})
            if verbose:
                for n in bot.last_notes:
                    note(f"[brain] {n}")
            if text:
                chat.append({"name": "Glue", "text": text, "ts": msg["ts"]})
                if verbose:
                    show("Glue", text, "bold red")
        tick = (start + timedelta(days=day, hours=3)).isoformat()
        text = bot.on_tick(tick)
        if verbose:
            for n in bot.last_notes:
                note(f"[brain] {n}")
        if text:
            chat.append({"name": "Glue", "text": text, "ts": tick})
            if verbose:
                show("Glue", text + f"  ({bot.history[-1]['kind']}: {bot.history[-1]['activity']})", "bold red")
    episode = {"group": group, "transcript": chat, "bot_messages": bot.history,
               "usage": dict(llm.USAGE), "playbook": bot.brain.playbook, "meetups": bot.meetups,
               "days": days, "start": start.isoformat(), "decisions": bot.decisions}
    episode["score"] = score(episode)
    return episode


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", default="train_1")
    ap.add_argument("--no-brain", action="store_true")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--days", type=int, default=14)
    a = ap.parse_args()
    ep = run_episode(load_group(a.group), brain_dir="brain", use_brain=not a.no_brain, days=a.days, seed=a.seed)
    print("\nscore:", ep["score"])
