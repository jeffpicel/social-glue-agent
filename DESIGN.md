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

### 5. Scoring: a confusion matrix weighted by one free value, w

For each activity and each week:

- **TP:** we proposed it, the group took it, and it was rated at or above the cutoff.
- **FP:** we proposed it and it wasn't a success. Reason: activity, timing, specifics, ignored, or low_rating.
- **FN:** the group wanted it, it hadn't happened recently, and we never offered it. The reason comes from the bot's own decision log: unexplored, misread, nudge_budget, waiting_for_quiet, no_availability, or not_due.
- **TN:** we didn't offer it and they didn't want it.

`score = (w·(TP − FN) + (1 − w)·(TN − FP)) / decisions`

- **One free parameter per group, w (0 to 1).** w is how much the group values meeting up: a hangout we made happen earns w, and one they wanted that we never offered costs w. 1 − w is how much they value not being messaged: a proposal that didn't land costs 1 − w, and correctly leaving them alone earns 1 − w. The default is 0.82 ("hangouts are rare and valuable").
- **Why one is enough:** proposing beats staying quiet when `p·(tp + fn) > (1 − p)·(fp + tn)`, so only the two sums ever affected a decision; how each sum split between its cells never did. Scaling both sums doesn't change which playbook scores higher, so only their ratio matters, and that is w. The bot proposes when its estimate exceeds `1 − w` (0.18 with the default, the same as before).
- **No message penalty for now.** It was deliberately light anyway, and a burst of back-and-forth to plan a trip is fine.
- **Gave up:** raw scores aren't comparable across groups, since w sets the scale. We don't learn across groups, so that's fine.
- **There are two versions of w:**
  - **True w:** what outcomes are really worth to the group. We never observe them, and they may be undiscoverable by nature, since this is a framework rather than a measurement. In the simulator it's hidden in the group JSON and used only to score.
  - **Operating estimate:** `brain/values.md`, our best guess at the true w. It drives what the bot does, and we want it to improve over time.
- **How to update the estimate is an open question** (see below). Today's rule is a placeholder: phrases in the chat nudge w ("that was so fun" and "it's been forever" raise it, "meh" and "too many pings" lower it).
- For now the reflector edits only the playbook, not w, so the N+1 loop can't raise its score by changing what it's judged on. How this fits with learning the estimates is part of the open question.
- w also drives decisions: a group that values hangouts more gets a bolder bot.
- **Rejected along the way:** four separate outcome values plus a message cost (only two sums ever mattered), an "annoyance" term (too loaded), plain accuracy (rewards silence, since most cells are TNs), and balanced accuracy (locks in fixed 50/50 weights).

### 5b. Every candidate gets an estimate; success means a good hangout

- For each thing it could propose (each call slot, each event found, each trip idea), the bot estimates **p_accept** (the chance enough people say yes) and **satisfaction** (the expected 0–10 rating from those who go). See `agents/estimator.py`: the model makes these estimates, with a heuristic fallback offline.
- **Success is not just a yes:** it's a hangout that happens *and* is rated at or above the cutoff (`success_cutoff: 7`, matching the 7/10 or 4/5 stars we'll ask real users for). So `p_success = p_accept × P(rating ≥ cutoff)`.
- **Decision:** take the best candidate and propose it only if `p_success` clears the threshold implied by the current value estimates. Otherwise probe instead of pushing.
- **Feedback:** after a hangout, attendees rate it 0–10. The rating moves the interest slider, and a hangout rated below the cutoff counts as an FP with reason `low_rating`.
- Each proposal stores its estimate, so the score reports **calibration** (Brier score on predicted vs. actual success) next to the outcomes.

### 5c. One kind of proposal: calls, events and trips are all event proposals (target design)

- Calls, local events (from Partiful, Luma or other sources) and group trips are all the same object, a **proposal**: what, when, where, cost, size of the ask (hours, travel, lead time), and source. **Why:** separate artifacts and frameworks per type are bloat, and don't scale to new sources.
- **Frequency comes from the estimate, not from types.** p_accept is conditioned on how long it has been since the group last did something of that size. A call a week after the last call scores well; a trip three months after the last trip scores low, and a year later scores high. Trips are rare because their p_success usually sits below `1 − w`, not because a rule says so.
- The per-activity sliders and cadence knobs become learned preferences over proposal features. "call", "event" and "trip" survive only as tags, for readable logs and for the per-(tag, week) cells in the score.
- **Status:** decided Oct 17, not yet built. The code still has separate sliders for call, event and trip; we kept it for the demo because GlueBot was live on Discord.

### 6. Pacing

- Only **ignored** nudges count against the weekly budget (`max_ignored_nudges_per_week`), so a busy planning week where people engage is never capped.
- All pacing knobs live in `playbook.md`: quiet-days waits, re-propose delay, probe frequency, learning rate, cadence per activity, and prior interest per activity.

### 7. Version N+1: per group, from its own history

- Each group's playbook improves from that group's own history. There is **no cross-group learning**, which would add scope and odd dependencies.
- Loop (`social_glue/evolve.py`): run the playbook on training seeds, have the reflector propose an edit, and keep it only if the training score improves. Then report v0 vs vN on **fresh seeds it never saw** (new chats of the same group, including its drift).
- The reflector sees the score with the FP and FN reasons, so it knows *why* it's losing.

### 8. Simulator

- `social_glue/sim/groups/*.json`: each group has members with hidden availability, interests and budget, plus a hidden **appetite** per activity that can **drift** mid-episode, and a hidden true **w** used for scoring.
- Personas reply in character, answer proposals and probes according to the appetite, and decline with a reason. After a hangout someone says how it went.
- `FAKE_LLM=1`, or no `CRUSOE_API_KEY`, runs everything offline with canned answers. Offline numbers only prove the plumbing works.

### 9. Infrastructure

- **Inference:** Crusoe Managed Inference (required by the hackathon), OpenAI-compatible at `https://api.inference.crusoecloud.com/v1`. Model ids are set by env var; see `.env.example` and PR #3 for the exact ids Crusoe accepts.
- **Events:** You.com search, cached to disk so the demo never stalls (`YOU_API_KEY`).
- **Deployment:** Discord (Thomas). The adapter only needs `Bot.on_message` per message and `Bot.on_tick` on a timer, with one `brain/` folder per channel (PR #4).

## Skills (tabled)

Proposed and parked for now: find_common_time, search_events, poll, propose_and_rsvp, remind; later search_destinations and recap. One idea was a `brain/skills/<name>.md` per skill that the reflector can rewrite.

## Open questions

- **How should the operating estimate of w be updated?** With one number per group this is smaller: for example a Beta prior on w, updated by ratings and by yes, no or ignored replies. We need a framework for this. Some candidates:
  - chat signals (today's placeholder)
  - explicit questions ("how did that go, 1–5?")
  - revealed preference (what the group says yes to, and how fast)
  - Bayesian updating with a prior per value
  - letting the N+1 loop propose value changes, judged against something it doesn't control

  Related: what do we score against outside the simulator, where the true w doesn't exist?
- The propose threshold is low with the default w (0.18), so trips get proposed without a probe. Do we want a separate "big ask" rule for trips?
- Real Crusoe numbers: the "First real Crusoe run" thread is producing them. Update this file with the v0 vs vN table when they land.
