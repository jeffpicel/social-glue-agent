# Social Glue

An agent that lives in a friends' group chat, keeps a **shared brain** of everyone's schedules and tastes, proposes calls, local events and trips, and **learns how pushy it's allowed to be**. It proves the improvement with scores on simulated friend groups it has never seen.

Built today at the Crusoe Recursive Agents Hackathon (Oct 17, 2026).

- **Version N+1 (primary):** a self-rewriting `brain/playbook.md` (when to nudge, how long to wait after a meetup, ask vs. propose, tone). Edits are kept only if they improve the score on held-out simulated groups.
- **Shared Brain (supporting):** living files (`brain/people/<name>.md`, `brain/group.md`) that every sub-agent reads before acting and a curator keeps current, lean and conflict-free.
- **Simulator:** LLM friend personas with hidden ground truth (availability, interests, budget, annoyance threshold) so we can measure plan quality, annoyance and tokens per call.

Inference runs on Crusoe Managed Inference; event search uses Serper/Google when configured, then You.com. The event search source registry is stored in `cache/search_sources.json`. Glue reviews every incoming group message for event-search source links. A direct request to use a source adds it immediately; incidental event links become active after appearing in two distinct messages. It also tracks which sources return search results and prioritizes the most useful ones. Every third uncached event search runs a broader discovery query; a new event-like domain is added after it returns results for two distinct queries. Event results are cached for six hours. Glue also extracts named venues from venue-related messages and saves them in `cache/venues.json`, including mention counts, website candidates, and reference pages. It uses Serper or You.com to find venue websites, then Yelp Places when configured for a fallback business listing. Cache files are local runtime data. When `YELP_API_KEY` is configured, Yelp Places search also adds specific local businesses to event venue and restaurant suggestions, alongside the existing event and reservation sources.

For dinner reservation requests, Glue searches public Resy/OpenTable booking pages, Yelp Places, and the MICHELIN Guide. It infers date and time from the request, recent chat context, and saved group availability; if those are missing, it defaults to the next suitable group day (or Friday) at 7pm. It infers party size from an explicit count, clear wording such as “my partner,” or known group-chat membership (minimum default: two). Before making suggestions, Glue uses SerpApi (`SERPAPI_API_KEY`) to match venues against Google Maps Popular Times, checks the typical busyness score for the inferred weekday/hour, and ranks checked venues from quieter to busier. It does not show Maps links. Popular Times are historical weekday/hour patterns, not forecasts for a specific future date. If the API key is missing or no venue has a matching Popular Times score, Glue does not suggest a restaurant. SerpApi usage may consume account credits. Listing pages are not live inventory: Glue does not claim seats are available and does not place reservations. Serper (`SERPER_API_KEY`) is tried first for web restaurant searches, with You.com as fallback. OpenTable's live APIs are partner integrations; a production availability checker needs approved provider access and should only recommend slots returned for the exact inferred date, time, and party size.

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
