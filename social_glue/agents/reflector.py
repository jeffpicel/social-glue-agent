"""Reflector: reads scored episodes and rewrites playbook.md (the Version N+1 step)."""
import re

from social_glue import llm

SYSTEM = """You tune the policy of Glue, a bot in a friends' group chat that proposes calls, events and trips.
You get the current playbook, a transcript, and its score: a confusion matrix over (activity, week) decisions.
- FP = proposed and declined; fp_reasons says why (activity = wrong kind of hangout, timing = wrong day/too soon,
  specifics = wrong event/place/price, ignored = nobody answered, low_rating = happened but rated below the cutoff).
- brier = how well the bot's own success estimates matched reality (lower is better).
- FN = the group wanted an activity and we never offered it; fn_reasons says why (unexplored = never probed a low
  belief, misread = probed but belief stayed low, nudge_budget / waiting_for_quiet / no_availability = wanted to
  propose but a gate blocked it, not_due = cadence too long).
- score = value of the outcomes per decision: w * (TP - FN) + (1 - w) * (TN - FP), where w is how much this group
  values meeting up versus not being messaged. You can't change w; change how the bot behaves.
Change the knobs and style lines to raise the score. Keep every "- key: number" knob line (code parses them)
and the markdown format. Return only the new playbook."""


def _set(playbook: str, key: str, fn) -> str:
    m = re.search(rf"{key}:\s*([\d.]+)", playbook)
    if not m:
        return playbook
    old = float(m.group(1))
    new = fn(old)
    new = int(new) if float(new).is_integer() else round(new, 2)
    return playbook.replace(m.group(0), f"{key}: {new}")


def _fake(playbook: str, s: dict) -> str:
    """Offline stand-in: simple rules over the same signals the model sees."""
    reasons = s.get("fp_reasons", {})
    if reasons.get("ignored", 0):
        playbook = _set(playbook, "max_ignored_nudges_per_week", lambda v: max(1, v // 2))
        playbook = _set(playbook, "repropose_after_days", lambda v: v + 2)
    if reasons.get("activity", 0) >= max(reasons.get("timing", 0), reasons.get("specifics", 0), 1):
        playbook = _set(playbook, "learning_rate", lambda v: min(0.6, v + 0.1))
    fn = s.get("fn_reasons", {})
    if fn.get("unexplored", 0):
        playbook = _set(playbook, "probe_every_days", lambda v: max(2, v - 2))
    if fn.get("misread", 0):
        playbook = _set(playbook, "learning_rate", lambda v: min(0.6, v + 0.1))
    if fn.get("waiting_for_quiet", 0):
        playbook = _set(playbook, "propose_after_quiet_days", lambda v: max(0, v - 1))
    if fn.get("nudge_budget", 0) and not reasons.get("ignored", 0):
        playbook = _set(playbook, "max_ignored_nudges_per_week", lambda v: v + 1)
    return playbook


def reflect(episode: dict) -> str:
    transcript = "\n".join(f"{m['name']}: {m['text']}" for m in episode["transcript"][-60:])
    user = f"PLAYBOOK:\n{episode['playbook']}\n\nSCORE: {episode['score']}\n\nTRANSCRIPT:\n{transcript}"
    return llm.chat(SYSTEM, user, tier="strong", fake=lambda: _fake(episode["playbook"], episode["score"]))
