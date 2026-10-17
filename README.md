# Social Glue

An agent that lives in a friends' group chat, keeps a **shared brain** of everyone's schedules and tastes, proposes calls, local events and trips, and **learns how pushy it's allowed to be**. It proves the improvement with scores on simulated friend groups it has never seen.

Built today at the Crusoe Recursive Agents Hackathon (Oct 17, 2026).

- **Shared Brain:** living files (`brain/people/<name>.md`, `brain/group.md`) that every sub-agent reads before acting and a curator keeps current, lean and conflict-free.
- **Version N+1:** a self-rewriting `brain/playbook.md` (nudge budget, ask vs. propose, tone). Edits are kept only if they improve the score on held-out simulated groups.
- **Simulator:** LLM friend personas with hidden ground truth (availability, interests, budget, annoyance threshold) so we can measure plan quality, annoyance and tokens per call.

Inference runs on Crusoe Managed Inference; event and destination search uses You.com.

## Coordinating

- [PLAN.md](PLAN.md): the build plan, architecture and demo script.
- [TASKS.md](TASKS.md): who's doing what. Humans and coding agents read it before starting and update it when done.

## Running

```bash
pip install -r requirements.txt
cp .env.example .env   # add Crusoe + You.com keys; leave empty to run offline with FAKE_LLM
python -m social_glue.bot   # scripted 5-message chat through listener -> curator -> governor -> planner
```

`sim/run.py` (simulated friend groups and scores) is next; see TASKS.md.
