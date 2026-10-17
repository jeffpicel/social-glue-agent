# Tasks

Shared task board for humans and coding agents. **Read this before starting work, and update it when you start or finish something.** Keep edits small and push often to avoid conflicts. Mark status as `todo`, `doing (<name>)`, or `done`.

Deadline: submit by **4:45 PM PT** (hard cutoff 5:00).

## Interface contract (frozen; change only after telling the other person)

- `Bot.on_message(msg: dict) -> str | None`
- `Persona.reply(chat: list[dict]) -> dict`
- `score(episode) -> dict` returning `plan_quality`, `annoyance`, `cost`, `score`
- Brain fact shape: `{value, source_msg, ts, confidence}`

## Ownership

- Jeff: `social_glue/llm.py`, `social_glue/brain.py`, `social_glue/agents/`
- Thomas: `social_glue/sim/`, `social_glue/evolve.py`, `social_glue/agents/reflector.py`

## Board

| Task | Owner | Status |
|---|---|---|
| `llm.py` working against Crusoe | Jeff | todo |
| Claim credits, You.com key | Thomas | todo |
| Brain file schema + 1 sample group JSON | Thomas | todo |
| `brain.py` read / patch / compact | Jeff | todo |
| `listener.py`, `curator.py` | Jeff | todo |
| `governor.py`, `planner.py` (+ You.com tool, cached) | Jeff | todo |
| `personas.py`, `run.py` rich chat loop | Thomas | todo |
| `score.py`, generate 6 groups (3 train, 3 heldout) | Thomas | todo |
| End-to-end episode on one group | Jeff | todo |
| `reflector.py` + `evolve.py` | Thomas | todo |
| Baseline vs brain, playbook v0 vs vN on heldout; save table | Thomas | todo |
| README: what was built today, how to run | Jeff | todo |
| Record 1-min video | Thomas | todo |
| Submit (repo public, video, both members) | Jeff | todo |

## Log

Append one line per finished task: `HH:MM name: what changed`.
