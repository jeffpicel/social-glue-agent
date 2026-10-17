"""Slack bot that hands @mentions to Claude Code running in your repo.

@mention the bot in a channel (or DM it) and it runs `claude -p` in REPO_DIR,
then replies in the thread. Follow-ups in the same thread resume the same
Claude Code session, so it keeps context.

Env vars:
  SLACK_BOT_TOKEN   xoxb-...  (OAuth & Permissions page)
  SLACK_APP_TOKEN   xapp-...  (Basic Information > App-Level Tokens, scope connections:write)
  REPO_DIR          path to your checkout (default: current directory)
  CLAUDE_PERMISSION_MODE  passed to --permission-mode (default: acceptEdits)

Run:  pip install slack_bolt && python bot.py
"""
import json
import os
import re
import subprocess

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

REPO_DIR = os.environ.get("REPO_DIR", os.getcwd())
PERMISSION_MODE = os.environ.get("CLAUDE_PERMISSION_MODE", "acceptEdits")
SLACK_LIMIT = 3900  # Slack truncates messages around 4000 chars

app = App(token=os.environ["SLACK_BOT_TOKEN"])
sessions: dict[str, str] = {}  # Slack thread ts -> Claude Code session id


def run_claude(prompt: str, thread_ts: str) -> str:
    cmd = ["claude", "-p", prompt, "--output-format", "json",
           "--permission-mode", PERMISSION_MODE]
    if thread_ts in sessions:
        cmd += ["--resume", sessions[thread_ts]]
    try:
        out = subprocess.run(cmd, cwd=REPO_DIR, capture_output=True,
                             text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return ":warning: Claude Code timed out after 10 minutes."
    if out.returncode != 0 and not out.stdout:
        return f":warning: claude exited {out.returncode}:\n```{out.stderr[-1500:]}```"
    try:
        data = json.loads(out.stdout)
    except json.JSONDecodeError:
        return out.stdout[-SLACK_LIMIT:] or "(no output)"
    if data.get("session_id"):
        sessions[thread_ts] = data["session_id"]
    return data.get("result") or "(no output)"


def handle(text: str, channel: str, thread_ts: str, say) -> None:
    prompt = re.sub(r"<@[A-Z0-9]+>", "", text).strip()
    if not prompt:
        say(text="Mention me with a task, e.g. `@claude what's left in TASKS.md?`",
            thread_ts=thread_ts)
        return
    say(text=":hourglass_flowing_sand: working on it...", thread_ts=thread_ts)
    answer = run_claude(prompt, thread_ts)
    for i in range(0, len(answer), SLACK_LIMIT):
        say(text=answer[i:i + SLACK_LIMIT], thread_ts=thread_ts)


@app.event("app_mention")
def on_mention(event, say):
    thread_ts = event.get("thread_ts") or event["ts"]
    handle(event["text"], event["channel"], thread_ts, say)


@app.event("message")
def on_dm(event, say):
    # Only DMs; channel messages without a mention are ignored.
    if event.get("channel_type") != "im" or event.get("bot_id") or event.get("subtype"):
        return
    thread_ts = event.get("thread_ts") or event["ts"]
    handle(event["text"], event["channel"], thread_ts, say)


if __name__ == "__main__":
    print(f"Claude Slack bot running in {REPO_DIR}")
    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()
