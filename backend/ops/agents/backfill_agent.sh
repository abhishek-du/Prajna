#!/usr/bin/env bash
# Headless Claude backfill agent (approved 2026-10-15). Cron runs it every morning (07:20
# IST) and the supervisor's alerts are its input. Tools are allowlisted: it can read files,
# read the supervisor status, run ONE supervisor tick, and write its report. Nothing else
# (no DB writes, no deletes, no cron/config/code edits, no network beyond Claude itself).
#
#   ops/agents/backfill_agent.sh
set -uo pipefail
cd "$(dirname "$0")/../.."
mkdir -p var/logs/backfill
CLAUDE="${PRAJNA_CLAUDE_BIN:-$HOME/.local/bin/claude}"
DAY="$(TZ=Asia/Kolkata date +%F)"
TMP="$(mktemp)"
"$CLAUDE" -p "$(cat ops/agents/backfill_agent_prompt.md)" \
  --permission-mode dontAsk \
  --allowedTools "Read" "Grep" "Glob" \
    "Edit(var/logs/backfill/**)" \
    "Bash(ops/runbooks/backfill_supervisor.sh status)" \
    "Bash(ops/runbooks/backfill_supervisor.sh tick)" \
    "Bash(tail:*)" "Bash(df:*)" "Bash(ls:*)" \
  --disallowedTools "NotebookEdit" "WebFetch" "WebSearch" \
  --output-format text \
  < /dev/null > "$TMP" 2>&1
rc=$?
cat "$TMP" >> "var/logs/backfill/agent_run_${DAY}.log"
# the agent uses the account's Claude usage; at the limit it does not run (the
# deterministic supervisor keeps the backfill going regardless) - say so explicitly
if grep -qiE "session limit|usage limit|rate limit" "$TMP"; then
  echo "[$(TZ=Asia/Kolkata date '+%F %T IST')] BACKFILL_AGENT_SKIPPED claude_usage_limit" \
    >> "var/logs/backfill/agent_run_${DAY}.log"; rm -f "$TMP"; exit 3
fi
rm -f "$TMP"
echo "[$(TZ=Asia/Kolkata date '+%F %T IST')] BACKFILL_AGENT_EXIT rc=${rc}" >> "var/logs/backfill/agent_run_${DAY}.log"
exit "$rc"
