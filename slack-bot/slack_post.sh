#!/usr/bin/env bash
# One-way status post from any coding agent: ./slack_post.sh "#build" "listener.py done, PR up"
# Optional 3rd arg sets the display name (needs chat:write.customize), e.g. "Thomas's Claude".
set -euo pipefail
CHANNEL="$1"; TEXT="$2"; NAME="${3:-claude}"
curl -sS https://slack.com/api/chat.postMessage \
  -H "Authorization: Bearer $SLACK_BOT_TOKEN" \
  -H "Content-Type: application/json; charset=utf-8" \
  -d "$(jq -n --arg c "$CHANNEL" --arg t "$TEXT" --arg u "$NAME" '{channel:$c,text:$t,username:$u}')" \
  | jq -r 'if .ok then "posted" else "error: \(.error)" end'
