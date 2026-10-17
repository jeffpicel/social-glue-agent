# Claude bot for Slack (free workspace, ~15 min)

`@claude <task>` in a channel runs Claude Code (`claude -p`) in your repo on your laptop and replies in the thread. Follow-ups in the same thread keep context. Uses Socket Mode, so no public URL or server.

## 1. Create the app (3 min)
1. Go to https://api.slack.com/apps and click **Create New App**, then **From an app manifest**.
2. Pick your hackathon workspace, choose **YAML**, paste [`manifest.yml`](manifest.yml), and click **Create**.
3. Click **Install to Workspace** (left sidebar: *Install App*) and click **Allow**.

## 2. Get the two tokens (2 min)
- **Bot token:** *OAuth & Permissions*, copy the **Bot User OAuth Token** (`xoxb-…`).
- **App token:** *Basic Information*, scroll to **App-Level Tokens**, click **Generate Token and Scopes**, name it `socket`, add scope `connections:write`, generate, and copy it (`xapp-…`).

## 3. Run the bot on your laptop (3 min)
```bash
cd ~/path/to/social-glue-agent          # your checkout
pip install slack_bolt
export SLACK_BOT_TOKEN=xoxb-...
export SLACK_APP_TOKEN=xapp-...
export REPO_DIR=$(pwd)
python slack-bot/bot.py                 # leave this terminal running
```
Claude Code must already be installed and logged in (`claude` works in that terminal).

## 4. Use it
1. In your channel, type `/invite @claude`.
2. Try `@claude summarize TASKS.md and say what's unowned`.
3. Reply in the thread to continue the same session. You can also DM the bot.

## Optional: agents posting status
Any Claude Code session can post one-way updates with:
```bash
./slack-bot/slack_post.sh "#build" "listener.py done, PR #3 up" "Jeff's Claude"
```
Tell your agents in `TASKS.md`/`CLAUDE.md`: "after finishing a task, run slack_post.sh with a one-line summary." Thomas needs the `SLACK_BOT_TOKEN` exported for this; he doesn't need to run `bot.py`.

## Notes
- **Permissions:** the bot runs with `--permission-mode acceptEdits` (it can edit files; shell commands that need approval will be refused). For more autonomy set `CLAUDE_PERMISSION_MODE=bypassPermissions`, but only in a throwaway checkout. Anyone in the workspace can drive it.
- **Two bots?** If Thomas wants his own Claude answering too, he repeats steps 1–3 with a different app name (e.g. `claude-thomas`).
- **Troubleshooting:** `not_in_channel`: invite the bot. `invalid_auth`: wrong token. No reply at all: check the terminal running `bot.py`.
