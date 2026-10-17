# Social Glue: hackathon build plan

Built for the Crusoe Recursive Agents Hackathon, Oct 17. Submissions due **5:00 PM PT**. Aim to submit by **4:45**.

## 1. Pitch (one line)
An agent that lives in a friends' group chat, keeps a **shared brain** of everyone's schedules and tastes, proposes calls, local events and trips, and **learns how pushy it's allowed to be**. It proves the improvement with scores on simulated friend groups it has never seen.

## 2. Track fit
- **Primary: Shared Brain.** The brain is a set of living files (one per person, plus one for the group) that every sub-agent reads before it acts and patches afterwards. Judges want to see three things here: the brain stays **current** (patches carry a timestamp and a source message), **lean** (a curator compacts and drops stale facts) and **conflict-free** (the curator resolves contradictions such as "Sam is free Tuesdays" vs. "Sam started a Tuesday class"). Show a **measurable gain**: plan quality and tokens per turn, with the brain vs. without it (raw transcript stuffed into the prompt).
- **Secondary: Version N+1.** "Learn not to overdo it" becomes a self-rewriting `playbook.md`: nudge budget, when to ask vs. propose, tone. After each simulated episode a Reflector proposes a playbook edit. The edit is **kept only if** it improves the score on held-out simulated groups. That gives a before/after number on unseen tasks, which is exactly what the track asks for.
- **Update 2:50 PM:** pitch it as **Version N+1 first**: a social agent that learns how pushy to be, proven by before/after scores on held-out groups. The shared brain is the substrate that makes that possible; show it, but don't lead with it.

## 3. The technical core: a friend-group simulator
Without real users you can't measure anything, so build **simulated friends** (LLM personas). The simulator is what makes this "beyond an average hackathon project".
- Each group has 3–5 personas with a **hidden ground truth**: weekly availability, interests, budget, travel willingness, and an **annoyance threshold** (how many bot messages a week before they get irritated or mute it).
- Personas only reveal info when asked or when it comes up naturally. They reply in character, and they react badly when the bot over-messages.
- Make about 6 groups: 3 for training the playbook, 3 held out for the before/after score. Generate them with an LLM once, then save them as JSON so runs are repeatable.

**Score per episode** (simulating about 2–3 weeks of chat):
- `plan_quality`: share of hidden constraints the final proposals satisfy (time works for everyone, event matches interests, within budget).
- `annoyance`: number of annoyed or mute reactions, plus bot messages beyond each person's threshold.
- `cost`: prompt tokens per agent call (this is the Shared Brain "lean" metric).
- `score = plan_quality - λ·annoyance` (report cost alongside it).

## 4. Architecture (Python, minimal)
```
social_glue/
  llm.py          # Crusoe Managed Inference client (OpenAI-compatible SDK; base URL + model ids from the hackathon repo)
  brain.py        # read/patch/compact brain files; each fact carries {value, source_msg, ts, confidence}
  agents/
    listener.py   # every chat message -> proposed brain patches (JSON)
    curator.py    # merges patches, resolves conflicts, compacts; the only writer to brain/
    planner.py    # proposes call slot / local event / trip; calls You.com search for real events & destinations
    governor.py   # decides whether to speak at all this turn, using playbook.md (nudge budget, quiet hours)
    reflector.py  # after an episode: reads transcript + score, proposes a playbook.md diff
  sim/
    personas.py   # persona agents with hidden ground truth
    groups/*.json # saved groups (train / heldout)
    run.py        # runs an episode: personas <-> bot in a simulated group chat, prints chat live
    score.py
  evolve.py       # N+1 loop: propose playbook edit -> eval on train -> keep if better -> final heldout before/after
brain/            # the live shared brain (git-tracked so the diff history is visible in the demo)
  people/<name>.md
  group.md        # cadence, past events, decisions, open questions
  playbook.md     # the bot's self-rewritten policy
```
- **Turn loop:** a persona message comes in, then Listener, then Curator patches the brain, then Governor decides whether to speak. If yes, Planner (reading the brain only, not the full transcript) writes a message.
- **Models:** use the strongest model in the Crusoe console for Planner/Curator/Reflector and a cheaper, faster one for personas and Listener. One API key, no other inference provider (Crusoe is required).
- **You.com:** Planner tool `search_events(city, interests, date_range)` and `search_destinations(origin, interests, budget)`. Cache results to disk so the live demo can't stall on the network.
- **Front end:** a terminal group chat rendered with `rich` (colored names, the bot in its own color), plus a split pane or a second terminal running `watch` on `brain/` so judges see the files change live. **No Streamlit, no dashboard.** If time allows, a tiny FastAPI + plain HTML chat page, but the terminal is enough.

## 5. Demo script (~3 min live)
1. **0:00–0:20 Hook.** "Every friend group has someone who does the planning. We built an agent that does it, and learns when to shut up." Show the group chat with 4 simulated friends.
2. **0:20–1:20 Shared Brain live.** Run an episode. Friends chat, the bot asks one smart question, and the brain files update on screen. Show one **conflict resolution** ("Maya: actually Thursdays are out now"): the curator rewrites the fact and cites the message.
3. **1:20–2:00 Proposals.** The bot proposes a recurring Sunday 7pm call, a real local event found through You.com that matches 3 of 4 interests, and a trip idea for a long weekend. The friends react.
4. **2:00–2:40 Version N+1.** Show the `playbook.md` git diff written by the Reflector (e.g. "max 2 unprompted messages/week; batch questions"). Show the before/after table on **held-out groups**: plan quality up, annoyance down, tokens per call down vs. the no-brain baseline.
5. **2:40–3:00 Close.** "The same pattern of a shared, curated brain plus a self-tuned proactivity policy works for any agent that lives among people." Say clearly that everything shown was built today.

Have the eval results **precomputed** and the live episode on a seed you've already tested. If the live episode is slow, cut to a recorded run.

**1-minute video:** 10s hook, 25s chat + brain updating, 15s playbook diff + before/after table, 10s architecture slide/README. Record it during a successful rehearsal run around 4:20.

## 6. Timeline (it's ~1:45 now)
| Time | Jeff | Thomas |
|---|---|---|
| 1:45–2:05 | Create public repo, skeleton, `llm.py` working against Crusoe | Claim credits, get You.com key, write the brain file schema + 1 sample group JSON |
| 2:05–3:15 | listener, curator, brain.py, governor, planner (+ You.com tool) | personas, run.py chat loop with rich, score.py, generate 6 groups |
| 3:15–3:45 | Integrate: full episode end-to-end on one group | reflector.py + evolve.py |
| 3:45–4:15 | Fix bugs, tune prompts, cache You.com results | Run baseline vs brain and playbook v0 vs vN on heldout; save the table |
| 4:15–4:35 | README (what was built today, how to run) | Record the 1-min video |
| 4:35–4:45 | Submit (repo public, video, both members added) | Rehearse the 3-min demo |

**Cut list if behind** (in this order): FastAPI page, then trip proposals, then the You.com live call (use cached results), then shrink evolve.py to a single reflect-and-compare round. **Never cut** the simulator score or the before/after table, since that's the "measurable" part.

**Freeze the interface contract in the first 15 minutes** so you can build in parallel:
- `Bot.on_message(msg: dict) -> str | None`
- `Persona.reply(chat: list[dict]) -> dict`
- `score(episode) -> dict`
- brain fact shape `{value, source_msg, ts, confidence}`

## 7. How the two of you + coding agents should coordinate
- **This Claude project can't add Thomas** (it's a single-owner private project), so it can't be the shared chatroom.
- **Lowest-friction setup:** keep your human chat where you already talk (iMessage/Discord). Make the **public GitHub repo the shared brain for the build**: put a `TASKS.md` with owners and the interface contract above at the root, and have each person's coding agent read it before starting and update it when done (yes, the same pattern as the product).
- Each of you runs your own coding agent (Claude Code locally, or a thread here for Jeff) on **your own branch / directory** (`social_glue/agents` vs `social_glue/sim`) to avoid merge conflicts. Push small and often, and merge to `main` every 30–45 min.
- Jeff can also drop asks in this project. Once the repo exists, a thread here can scaffold code and open PRs against it.
