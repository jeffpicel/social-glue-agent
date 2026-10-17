# Social Glue: design vision, goals and decisions

A record of what we decided while designing the harness on Oct 17 (Jeff, with Claude). Thomas: please review, and add a line under **Open questions** for anything you'd change. PLAN.md is the original morning plan; where the two disagree, this file wins.

## Vision

Every friend group has someone who does the planning. Social Glue is a bot that sits in the group chat and does that job: it keeps a shared memory of everyone's schedules and tastes, suggests hangouts, and learns, per group, what kind of help the group actually wants and how much of it.

Friend groups differ. Some only want a regular call and help finding a time when plans shift. Some want to go to live events together. Some want one big trip a year. Some want all of it, and groups change over time. The bot must not push an annual trip on a group that doesn't want one.

## What success looks like

Success depends on the group, so it is not a fixed target. The group should get the kinds of hangouts it wants, at roughly the rhythm it wants, without being pushed toward things it doesn't want. Missing a good hangout is worse than proposing something people turn down, because hangouts are rare and valuable.

## Hackathon framing

- **Primary track: Version N+1.** The bot rewrites its own playbook after scored runs and keeps an edit only if it measurably helps. The proof is a v0 vs vN score on runs it hasn't seen.
- **Supporting: Shared Brain.** The brain files are what make learning possible, so we show them, but we don't lead with them.

## Decisions

### 1. Architecture: two entry points, one brain

- `Bot.on_message(msg)` reacts to the chat. Pipeline: listener (extracts facts) → curator (the only writer to `brain/`; resolves conflicts, keeps files lean) → tracker (reads replies to proposals) → governor (speak or not) → planner (writes the message).
- `Bot.on_tick(now)` is called on a clock (hourly in Discord, nightly in the sim). It is the bot's only way to start things: it proposes or probes when something is due.
- **Why the timer path exists:** the bot shouldn't only react. It has to restart a quiet chat, and it should be driven mainly by time since the group last met, not just by chat silence.

### 2. Memory: the brain folder, not the transcript

- `brain/people/<name>.md`, `brain/group.md`, `brain/interests.md`, `brain/values.md`, `brain/playbook.md`. Every fact carries `{value, source_msg, ts, confidence}`.
- Agents see the brain plus the last few messages, not the whole transcript. **Why:** cost and speed (a transcript grows forever, a curated brain doesn't). It's not a safety rule, and the folder isn't fixed: add files whenever they help.

### 3. What the group wants: interest sliders, not group types

- We rejected hard group types ("call-only", "events crew"…) as too rigid, because groups morph.
- Instead `brain/interests.md` holds a 0–1 slider per activity (call, event, trip). It's a classic recommendations / explore-exploit setup:
  - **High slider: exploit.** Propose the activity when it's due by cadence; yes, no and silence are the feedback.
  - **Low slider: explore.** We'd never get feedback by not proposing, so the bot occasionally sends a light, no-pressure probe ("would anyone be into a trip this year?"). Groups drift, so probing never fully stops.

### 4. Every "no" has a reason

A decline is classified, and each reason updates a different part of the brain, so one bad event idea doesn't kill the events slider:

| reason | example | what changes |
|---|---|---|
| activity | "not really into trips" | interest slider down |
| timing | "can't do Tuesday", "too soon" | availability / cadence; slider mostly kept |
| specifics | "more into live music", "too expensive" | that person's tastes; slider mostly kept |

Silence for a day counts as a weak no.

### 5. Scoring: a confusion matrix with free outcome values

For each activity and each week:

- **TP:** we proposed it and the group took it.
- **FP:** we proposed it and it wasn't taken. Reason: activity, timing, specifics or ignored.
- **FN:** the group wanted it, it hadn't happened recently, and we never offered it. The reason comes from the bot's own decision log: unexplored, misread, nudge_budget, waiting_for_quiet, no_availability, or not_due.
- **TN:** we didn't offer it and they didn't want it.

`score = (tp·TP + tn·TN − fp·FP − fn·FN) / decisions − msg × bot messages`

- The outcome values are **free parameters per group**, in `brain/values.md`. Defaults follow "hangouts are rare and valuable": tp 1.0 > fn 0.6 > fp 0.3 > tn 0.05, and msg 0.005.
- **The message penalty is deliberately light.** A burst of back-and-forth to plan a trip is fine.
- The values are learned from what the group says ("that was so fun" raises tp, "it's been forever" raises fn, "too many pings" raises fp and msg).
- **The reflector can't edit the values**, only behavior. Otherwise the N+1 loop could raise its score by lowering the costs it's judged on.
- The values also drive decisions. The bot proposes when its interest estimate exceeds `(fp + tn) / (tp + fn + fp + tn)`, the point where proposing has the higher expected value. A group that values hangouts more gets a bolder bot.
- **Rejected along the way:** an "annoyance" term (too loaded), plain accuracy (rewards silence, since most cells are TNs), and balanced accuracy (locks in fixed 50/50 weights).

### 6. Pacing

- Only **ignored** nudges count against the weekly budget (`max_ignored_nudges_per_week`), so a busy planning week where people engage is never capped.
- All pacing knobs live in `playbook.md`: quiet-days waits, re-propose delay, probe frequency, learning rate, cadence per activity, and prior interest per activity.

### 7. Version N+1: per group, from its own history

- Each group's playbook improves from that group's own history. There is **no cross-group learning**, which would add scope and odd dependencies.
- Loop (`social_glue/evolve.py`): run the playbook on training seeds, have the reflector propose an edit, and keep it only if the training score improves. Then report v0 vs vN on **fresh seeds it never saw** (new chats of the same group, including its drift).
- The reflector sees the score with the FP and FN reasons, so it knows *why* it's losing.

### 8. Simulator

- `social_glue/sim/groups/*.json`: each group has members with hidden availability, interests and budget, plus a hidden **appetite** per activity that can **drift** mid-episode, and hidden true **values** used for scoring.
- Personas reply in character, answer proposals and probes according to the appetite, and decline with a reason. After a hangout someone says how it went.
- `FAKE_LLM=1`, or no `CRUSOE_API_KEY`, runs everything offline with canned answers. Offline numbers only prove the plumbing works.

### 9. Infrastructure

- **Inference:** Crusoe Managed Inference (required by the hackathon), OpenAI-compatible at `https://api.inference.crusoecloud.com/v1`. Model ids are set by env var; see `.env.example` and PR #3 for the exact ids Crusoe accepts.
- **Events:** You.com search, cached to disk so the demo never stalls (`YOU_API_KEY`).
- **Deployment:** Discord (Thomas). The adapter only needs `Bot.on_message` per message and `Bot.on_tick` on a timer, with one `brain/` folder per channel (PR #4).

## Skills (tabled)

Proposed and parked for now: find_common_time, search_events, poll, propose_and_rsvp, remind; later search_destinations and recap. One idea was a `brain/skills/<name>.md` per skill that the reflector can rewrite.

## Open questions

- Should the outcome values also be learned from explicit questions ("how did that go, 1–5?") rather than only from chat phrases?
- The values-derived propose threshold is low with the defaults (0.18), so trips get proposed without a probe. Do we want a separate "big ask" rule for trips?
- Real Crusoe numbers: the "First real Crusoe run" thread is producing them. Update this file with the v0 vs vN table when they land.
