# Social Glue

An agent that lives in a friends' group chat, keeps a **shared brain** of everyone's schedules and tastes, proposes calls, local events and trips, and **learns how pushy it's allowed to be**. It proves the improvement with scores on simulated friend groups it has never seen.

Built today at the Crusoe Recursive Agents Hackathon (Oct 17, 2026).

- **Version N+1 (primary):** a self-rewriting `brain/playbook.md` (when to nudge, how long to wait after a meetup, ask vs. propose, tone). Edits are kept only if they improve the score on held-out simulated groups.
- **Shared Brain (supporting):** living files (`brain/people/<name>.md`, `brain/group.md`) that every sub-agent reads before acting and a curator keeps current, lean and conflict-free.
- **Simulator:** LLM friend personas with hidden ground truth (availability, interests, budget, annoyance threshold) so we can measure plan quality, annoyance and tokens per call.

Inference runs on Crusoe Managed Inference; event and destination search uses You.com.

## Coordinating

- [DESIGN.md](DESIGN.md): design vision, goals and decisions (start here).
- [PLAN.md](PLAN.md): the original morning build plan and demo script.
- [TASKS.md](TASKS.md): who's doing what. Humans and coding agents read it before starting and update it when done.

## Running

```bash
pip install -r requirements.txt
cp .env.example .env   # add Crusoe + You.com keys; leave empty to run offline with FAKE_LLM
python -m social_glue.bot   # scripted 5-message chat through listener -> curator -> governor -> planner

python -m social_glue.sim.run --group train_1          # simulated 2-week group chat, brain/ updates live
python -m social_glue.sim.run --group heldout_1 --no-brain
python -m social_glue.evolve --all --rounds 3          # per group: reflect, keep playbook edits that help, v0 vs vN on unseen runs -> results/
```
