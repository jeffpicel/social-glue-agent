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
    bot.brain.write("group", {"location": {"value": group["city"], "source_msg": "setup", "ts": "2026-10-01T00:00:00", "confidence": 1.0}})
    personas = [Persona(m, rng) for m in group["members"]]
    color = {p.name: COLORS[i % len(COLORS)] for i, p in enumerate(personas)}
    chat, reactions = [], []
    start = datetime(2026, 10, 1, 18)
    for day in range(days):
        for turn in range(2):
            p = rng.choice(personas)
            msg = p.reply(chat)
            msg["ts"] = (start + timedelta(days=day, hours=turn)).isoformat()
            chat.append(msg)
            if msg["reaction"] != "none":
                reactions.append(msg["reaction"])
            if verbose:
                show(p.name, msg["text"] + ("" if msg["reaction"] == "none" else f"  [{msg['reaction']}]"), color[p.name])
            text = bot.on_message({k: msg[k] for k in ("name", "text", "ts")})
            if verbose:
                for n in bot.last_notes:
                    note(f"[curator] {n}")
            if text:
                chat.append({"name": "Glue", "text": text, "ts": msg["ts"]})
                if verbose:
                    show("Glue", text, "bold red")
    episode = {"group": group, "transcript": chat, "reactions": reactions, "bot_messages": bot.history,
               "usage": dict(llm.USAGE), "playbook": bot.brain.playbook}
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
