"""Reflector: reads a scored episode and rewrites playbook.md (the Version N+1 step)."""
import re

from social_glue import llm

SYSTEM = """You tune the policy of Glue, a bot in a friends' group chat that plans hangouts.
You get the current playbook, an episode transcript, and its score (plan_quality up is good, annoyance up is bad).
Rewrite the playbook to score better next time: adjust max_unprompted_per_week, when to ask vs propose, tone.
Keep the line "- max_unprompted_per_week: N" and the markdown bullet format. Return only the new playbook."""


def _fake(playbook: str, s: dict) -> str:
    m = re.search(r"max_unprompted_per_week:\s*(\d+)", playbook)
    n = int(m.group(1)) if m else 3
    if s["annoyance"] > 0:
        playbook = playbook.replace(f"max_unprompted_per_week: {n}", f"max_unprompted_per_week: {max(1, n // 2)}")
        if "Batch" not in playbook:
            playbook += "- Batch: one message that asks everyone missing info at once beats several one-person questions.\n"
    elif s["plan_quality"] < 0.7 and n < 6:
        playbook = playbook.replace(f"max_unprompted_per_week: {n}", f"max_unprompted_per_week: {n + 1}")
    return playbook


def reflect(episode: dict) -> str:
    transcript = "\n".join(f"{m['name']}: {m['text']}" for m in episode["transcript"][-60:])
    user = f"PLAYBOOK:\n{episode['playbook']}\n\nSCORE: {episode['score']}\n\nTRANSCRIPT:\n{transcript}"
    return llm.chat(SYSTEM, user, tier="strong", fake=lambda: _fake(episode["playbook"], episode["score"]))
