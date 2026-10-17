# Tasks

Shared task board for humans and coding agents. **Read this before starting work, and update it when you start or finish something.** Keep edits small and push often to avoid conflicts. Mark status as `todo`, `doing (<name>)`, or `done`.

Deadline: submit by **4:45 PM PT** (hard cutoff 5:00).

## Re-scope (2:30 PM)

Thomas is on the Slack bot for team coordination, so the simulator has no owner. Jeff (plus coding agents) now owns the **whole harness**, and the simulator shrinks to the thinnest version that still produces a before/after number. If Thomas frees up, he picks up anything under `sim/` marked `todo`.

**Vision in one breath:** a bot sits in a friend group chat. Every message goes through one pipeline (listen, curate, decide whether to speak, plan). Its memory is the brain folder (per-friend files, group, playbook, plus any other files that help, e.g. past proposals) and the last few messages, rather than the whole transcript, so prompts stay small as the chat grows. A playbook file controls how pushy it is, and one reflect step rewrites that playbook from a scored episode.

## Harness structure

```
social_glue/
  llm.py            # Crusoe Managed Inference (OpenAI-compatible). FAKE_LLM=1 returns canned JSON so everything runs offline.
  brain.py          # load/save brain/ files; facts are {value, source_msg, ts, confidence}
  bot.py            # Bot.on_message(msg) -> str | None : the pipeline below
  agents/
    listener.py     # msg -> list of proposed fact patches (cheap model)
    curator.py      # apply patches, resolve conflicts, drop stale facts; only writer to brain/
    governor.py     # speak or stay quiet? reads playbook.md + bot message count this week
    planner.py      # writes the message from brain only; tools: search_events (You.com, cached to disk)
    reflector.py    # transcript + score -> playbook.md edit
  sim/
    groups/*.json   # personas with hidden truth (availability, interests, budget, annoyance_threshold)
    personas.py     # Persona.reply(chat) -> {name, text, reaction}
    run.py          # episode loop, prints chat with rich; --no-brain baseline flag
    score.py        # plan_quality, annoyance, cost, score
  evolve.py         # one round: run train group, reflect, rerun heldout with new playbook, print table
brain/
  people/<name>.md
  group.md
  playbook.md
```

Two paths share the brain:
- Message: persona message → listener → curator patches brain → governor decides → (if speaking) planner writes from brain.
- Timer: `on_tick` each evening → governor weighs days since the last meetup (vs. `target_meetup_every_days`) first and chat silence second, within the weekly budget → planner proposes (or asks if it can't propose yet).
- Meetups: `agents/tracker.py` marks a plan confirmed when a majority says yes and writes `last_meetup` to `group.md`.

## Interface contract (frozen; change only after telling the other person)

- `Bot.on_message(msg: dict) -> str | None` where `msg = {name, text, ts}`
- `Bot.on_tick(now: str) -> str | None`: called on a clock; lets the bot restart a quiet chat (playbook `nudge_after_quiet_days`)
- `Persona.reply(chat: list[dict]) -> dict` returning `{name, text, reaction}` (`reaction` in `none | annoyed | muted`)
- `score(episode) -> dict` returning `plan_quality`, `annoyance`, `cost`, `score`
- Brain fact shape: `{value, source_msg, ts, confidence}`

## Board

| Time (PT) | Task | Owner | Status |
|---|---|---|---|
| 2:30–2:45 | Agree vision + structure (this file) | Jeff | done |
| 2:30–2:45 | Package skeleton, `llm.py` with Crusoe + FAKE_LLM fallback, `brain.py` | Jeff | done |
| 2:30–2:45 | Crusoe API key + model ids in `.env`; You.com key | Jeff | todo |
| 2:45–3:30 | `listener.py`, `curator.py` (incl. one conflict case): v0 runs in fake mode; tune prompts on Crusoe | Jeff | doing (Jeff) |
| 2:45–3:30 | `governor.py`, `planner.py` + cached `search_events`: v0 runs in fake mode; tune on Crusoe | Jeff | doing (Jeff) |
| 3:30–4:00 | Thin sim: 3 group JSONs (1 train, 2 heldout), `personas.py`, `run.py` | Claude | done (offline) |
| 3:30–4:00 | `score.py` + `--no-brain` baseline | Claude | done (offline) |
| 4:00–4:15 | `reflector.py` + `evolve.py` (one round), save results table | Claude | code done; real run needs Crusoe keys |
| next | Run `python -m social_glue.evolve` on Crusoe, commit `results/` | Jeff | todo |
| 4:15–4:30 | README: what was built today, how to run | Jeff | todo |
| 4:15–4:30 | Record 1-min video | Thomas | todo |
| 4:35–4:45 | Submit (repo public, video, both members) | Jeff | todo |
| side | Slack bot for team coordination (PR #1) | Thomas | doing (Thomas) |

**Cut list if behind** (in order): trip proposals, live You.com calls (cached only), heldout drops to 1 group, evolve becomes a hand-shown playbook diff. **Never cut** the brain-vs-no-brain number.

## Log

Append one line per finished task: `HH:MM name: what changed`.

- 14:35 Claude: re-scoped board after Thomas moved to the Slack bot; harness structure written down.
- 14:55 Claude: harness v0 pushed: `python -m social_glue.bot` runs the full pipeline offline (FAKE_LLM), incl. the Thursday conflict.
- 15:10 Claude: sim, score, reflector and evolve run offline. Fake-mode numbers are placeholders; real before/after needs Crusoe.
- 15:00 Claude: added `Bot.on_tick` timer path so the bot proposes after a quiet stretch (Jeff's call).
- 15:15 Claude: timer now driven by time since last meetup; tracker records confirmed plans; annoyance is per-week. Offline evolve run keeps a playbook edit that cuts held-out annoyance 4.5 -> 0.
