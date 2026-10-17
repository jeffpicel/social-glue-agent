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

- max_unprompted_per_week: 6
- nudge_after_quiet_days: 3
- overdue_nudge_after_quiet_days: 1
- target_meetup_every_days: 14
- Ask at most one question per message; batch questions for several people together.
- Propose a concrete plan (time + place) once at least two people have shared availability.
- Stay quiet while people are chatting about something else.
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
