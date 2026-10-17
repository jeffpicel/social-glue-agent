"""What outcomes are worth to this group: the free parameters behind both the score and the bot's decisions.

brain/values.md holds the bot's current estimates:
  tp  benefit of a hangout that happens because we proposed it   (highest: hangouts are rare and valuable)
  fn  cost of a hangout they wanted that we never offered         (high: missing one is worse than a "no")
  fp  cost of a proposal they turn down                           (lower)
  tn  benefit of correctly leaving them alone                     (lowest)
  msg cost per bot message                                        (light: planning bursts are fine)

They're updated from what the group says (a great hangout, "it's been forever", "too many pings"), never by the
reflector, so the N+1 loop can't make its own job easier by lowering the costs it's judged on.
The bot proposes an activity when expected value says so: p*tp - (1-p)*fp > (1-p)*tn - p*fn,
i.e. when its interest estimate p exceeds (fp + tn) / (tp + fn + fp + tn).
"""
import json
import re

from social_glue.brain import Brain

DEFAULT = {"tp": 1.0, "fn": 0.6, "fp": 0.3, "tn": 0.05, "msg": 0.005}
RANGE = {"tp": (0.3, 2.0), "fn": (0.1, 1.5), "fp": (0.05, 1.0), "tn": (0.0, 0.3), "msg": (0.0, 0.05)}
RATE = 0.25

SIGNALS = [  # (pattern, key, direction)
    (re.compile(r"so fun|was great|was amazing|best night|loved it|do (that|it) more", re.I), "tp", +1),
    (re.compile(r"\bmeh\b|was ok\b|kinda boring|not worth", re.I), "tp", -1),
    (re.compile(r"been forever|we should (hang|do something|get together)|miss (you|y'all|everyone)|haven't (seen|hung)", re.I), "fn", +1),
    (re.compile(r"too many (messages|pings)|stop (pinging|asking)|chill (out|glue)|spam", re.I), "fp", +1),
    (re.compile(r"too many (messages|pings)|so many messages|stop (pinging|asking)", re.I), "msg", +1),
]


def load(brain: Brain) -> dict:
    p = brain.root / "values.md"
    m = re.search(r"<!-- values: (.*?) -->", p.read_text(), re.S) if p.exists() else None
    v = json.loads(m.group(1)) if m else {}
    return {**DEFAULT, **v}


def save(brain: Brain, v: dict) -> None:
    lines = [f"<!-- values: {json.dumps(v)} -->", "# What outcomes are worth to this group", ""]
    names = {"tp": "hangout we made happen", "fn": "missed hangout they wanted", "fp": "proposal turned down",
             "tn": "correctly left alone", "msg": "each bot message"}
    for k, label in names.items():
        sign = "+" if k in ("tp", "tn") else "-"
        lines.append(f"- **{k}** ({label}): {sign}{v[k]:.3g}")
    lines.append(f"\nPropose when interest > {threshold(v):.2f}")
    (brain.root / "values.md").write_text("\n".join(lines) + "\n")


def threshold(v: dict) -> float:
    return (v["fp"] + v["tn"]) / (v["tp"] + v["fn"] + v["fp"] + v["tn"])


def learn(brain: Brain, text: str) -> list[str]:
    """Nudge value estimates from what people say. Returns notes for the demo."""
    v, notes = load(brain), []
    for pattern, key, direction in SIGNALS:
        if pattern.search(text):
            lo, hi = RANGE[key]
            old = v[key]
            target = hi if direction > 0 else lo
            v[key] = round(old + RATE * (target - old), 4)
            notes.append(f"value.{key}: {old:.3g} -> {v[key]:.3g}")
    if notes:
        save(brain, v)
    return notes
