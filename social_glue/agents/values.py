"""What outcomes are worth to this group: one free parameter behind both the score and the bot's decisions.

brain/values.md holds the bot's current estimate of w, between 0 and 1:
  w      how much the group values meeting up: the gain of a hangout we made happen (TP), and equally the
         cost of one they wanted that we never offered (FN)
  1 - w  how much the group values not being messaged: the cost of a proposal that didn't land (FP), and equally
         the gain of correctly leaving them alone (TN)

Why one number: the bot proposes when p*(tp + fn) > (1-p)*(fp + tn), so only those two sums ever affect a decision,
and scaling both doesn't change which playbook scores higher. That leaves their ratio, w.
The bot proposes when its estimate p exceeds 1 - w. The default w = 0.82 says hangouts are rare and valuable.

w is updated from what the group says (a great hangout, "it's been forever", "too many pings"), never by the
reflector, so the N+1 loop can't make its own job easier by changing what it's judged on.
"""
import json
import re

from social_glue.brain import Brain

DEFAULT = {"w": 0.82}
RANGE = (0.5, 0.97)
RATE = 0.25

SIGNALS = [  # (pattern, direction)
    (re.compile(r"so fun|was great|was amazing|best night|loved it|do (that|it) more", re.I), +1),
    (re.compile(r"been forever|we should (hang|do something|get together)|miss (you|y'all|everyone)|haven't (seen|hung)", re.I), +1),
    (re.compile(r"\bmeh\b|was ok\b|kinda boring|not worth", re.I), -1),
    (re.compile(r"too many (messages|pings)|so many messages|stop (pinging|asking)|chill (out|glue)|spam", re.I), -1),
]


def normalize(v: dict) -> dict:
    """Accept the old four-value form ({tp, fn, fp, tn}) and collapse it to w."""
    if "w" not in v and all(k in v for k in ("tp", "fn", "fp", "tn")):
        meet = v["tp"] + v["fn"]
        return {"w": round(meet / (meet + v["fp"] + v["tn"]), 4)}
    return {**DEFAULT, **{k: v[k] for k in ("w",) if k in v}}


def load(brain: Brain) -> dict:
    p = brain.root / "values.md"
    m = re.search(r"<!-- values: (.*?) -->", p.read_text(), re.S) if p.exists() else None
    return normalize(json.loads(m.group(1)) if m else {})


def save(brain: Brain, v: dict) -> None:
    lines = [f"<!-- values: {json.dumps(v)} -->", "# What outcomes are worth to this group", "",
             f"- **w** (meeting up: a hangout we made happen, or one we missed): {v['w']:.3g}",
             f"- **1 - w** (not being messaged: a proposal that didn't land, or leaving them alone): {1 - v['w']:.3g}",
             f"\nPropose when interest > {threshold(v):.2f}"]
    (brain.root / "values.md").write_text("\n".join(lines) + "\n")


def threshold(v: dict) -> float:
    return 1 - v["w"]


def learn(brain: Brain, text: str) -> list[str]:
    """Nudge the estimate of w from what people say. Returns notes for the demo."""
    v, notes = load(brain), []
    for pattern, direction in SIGNALS:
        if pattern.search(text):
            old = v["w"]
            target = RANGE[1] if direction > 0 else RANGE[0]
            v["w"] = round(old + RATE * (target - old), 4)
            notes.append(f"value.w: {old:.3g} -> {v['w']:.3g}")
    if notes:
        save(brain, v)
    return notes
