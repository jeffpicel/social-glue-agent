"""The shared brain: one markdown file per person, group.md, and playbook.md.

Facts are stored as JSON in an HTML comment at the top of each file and rendered as readable
markdown below it, so judges can watch the files change and code can parse them back.
Fact shape: {value, source_msg, ts, confidence}, keyed by a short slug like "availability".
"""
import json
import re
from pathlib import Path

FACTS_RE = re.compile(r"<!-- facts: (.*?) -->", re.S)

DEFAULT_PLAYBOOK = """# Playbook

## Knobs (code reads these; the reflector tunes them)
(When to propose vs. probe comes from brain/values.md, which the reflector doesn't touch.)
- max_ignored_nudges_per_week: 6
- propose_after_quiet_days: 1
- probe_after_quiet_days: 2
- repropose_after_days: 2
- probe_every_days: 7
- learning_rate: 0.3
- cadence_days_call: 7
- cadence_days_event: 14
- cadence_days_trip: 90
- prior_interest_call: 0.5
- prior_interest_event: 0.4
- prior_interest_trip: 0.2

## Style (the planner reads these)
- Ask at most one question per message; batch questions for several people together.
- Proposals are concrete (day + time + place) and easy to say yes or no to.
- Probes are light and no-pressure; never propose specifics in a probe.
- Keep messages under 40 words, casual tone.
"""


class Brain:
    def __init__(self, root="brain"):
        self.root = Path(root)
        (self.root / "people").mkdir(parents=True, exist_ok=True)
        if not (self.root / "playbook.md").exists():
            (self.root / "playbook.md").write_text(DEFAULT_PLAYBOOK)
        self.log = []  # human-readable curator notes for the demo

    def _path(self, who: str) -> Path:
        return self.root / "group.md" if who == "group" else self.root / "people" / f"{who.lower()}.md"

    def facts(self, who: str) -> dict:
        p = self._path(who)
        if not p.exists():
            return {}
        m = FACTS_RE.search(p.read_text())
        return json.loads(m.group(1)) if m else {}

    def people(self) -> list[str]:
        return sorted(p.stem for p in (self.root / "people").glob("*.md"))

    def write(self, who: str, facts: dict) -> None:
        title = "Group" if who == "group" else who.capitalize()
        lines = [f"<!-- facts: {json.dumps(facts)} -->", f"# {title}", ""]
        for key, f in facts.items():
            lines.append(f"- **{key}**: {f['value']}  \n  _\"{f['source_msg']}\" ({f['ts']}, conf {f['confidence']})_")
        self._path(who).write_text("\n".join(lines) + "\n")

    @property
    def playbook(self) -> str:
        return (self.root / "playbook.md").read_text()

    @playbook.setter
    def playbook(self, text: str) -> None:
        (self.root / "playbook.md").write_text(text)

    def render(self) -> str:
        """Compact text of the whole brain, which is all the planner ever sees."""
        out = []
        for who in ["group", *self.people()]:
            fs = self.facts(who)
            if fs:
                out.append(f"[{who}] " + "; ".join(f"{k}: {v['value']}" for k, v in fs.items()))
        return "\n".join(out) or "(brain is empty)"

    def reset(self) -> None:
        for p in (self.root / "people").glob("*.md"):
            p.unlink()
        if (self.root / "group.md").exists():
            (self.root / "group.md").unlink()
