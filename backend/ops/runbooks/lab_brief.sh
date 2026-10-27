#!/usr/bin/env bash
# Strategy Lab morning brief (user 2026-10-27; docs/STRATEGY_LAB.md): the P1 regime call,
# events, results today, the S1/S2 setups with their present condition, the E5 picks once
# made, and high-impact news. Unvalidated research signals, not advice; no order.
#
#   ops/runbooks/lab_brief.sh
#
# Cron (weekdays): 08:30 (after the 07:00 daily bars) and 09:10 (adds the 09:06 E5 picks and
# sends the AI-written intraday Buy List to Telegram)
#   30 8 * * 1-5   cd $B && ops/runbooks/lab_brief.sh >> var/logs/cron.log 2>&1
#   10 9 * * 1-5   cd $B && ops/runbooks/lab_brief.sh >> var/logs/cron.log 2>&1
set -uo pipefail
cd "$(dirname "$0")/../.."
P="${PRAJNA_PY:-.venv/bin/python}"
NOTIFY="${PRAJNA_TELEGRAM_CMD:-ops/runbooks/telegram_notify.sh}"
mkdir -p var/logs/lab var/run
DAY="$(TZ=Asia/Kolkata date +%F)"; OUT="var/logs/lab/brief_${DAY}_$(TZ=Asia/Kolkata date +%H%M).json"
say() { echo "[$(TZ=Asia/Kolkata date '+%F %T IST')] $*"; }
exec 9> var/run/lab_brief.lock
flock -n 9 || { say "LAB_BRIEF_SKIP another brief holds var/run/lab_brief.lock"; exit 0; }
export PRAJNA_SUPPLIED_TOKEN="$(grep '^PRAJNA_WRITE_TOKEN=' .env 2>/dev/null | cut -d= -f2-)"
say "LAB_BRIEF_START"
if "$P" -m app.cli.main --plain lab brief --commit > "$OUT" 2>&1; then
  rc=0; say "LAB_BRIEF_OK $(grep -o '"status": "[A-Z_]*"' "$OUT" | head -1)"
  # the 09:10 run (after the E5 picks) sends the AI-written Buy List to Telegram
  if [[ "$(TZ=Asia/Kolkata date +%H%M)" > "0900" && "$(TZ=Asia/Kolkata date +%H%M)" < "0915" ]]; then
    AWS_BEARER_TOKEN_BEDROCK="$(grep '^AWS_BEARER_TOKEN_BEDROCK=' .env 2>/dev/null | cut -d= -f2-)"
    export AWS_BEARER_TOKEN_BEDROCK
    msg="$("$P" -m app.lab.telegram_ai MORNING 2>/dev/null)"
    unset AWS_BEARER_TOKEN_BEDROCK
    if [[ -n "$msg" ]]; then "$NOTIFY" "$msg" >/dev/null 2>&1 && say "LAB_BRIEF_TELEGRAM sent"; fi
  fi
else
  rc=1; why="$(grep -m1 REFUSED "$OUT" | cut -c1-300)"
  say "LAB_BRIEF_ALERT ${why:-failed (see ${OUT})}"
  "$NOTIFY" "Prajna morning brief ISSUE: ${why:-failed}" >/dev/null 2>&1
fi
unset PRAJNA_SUPPLIED_TOKEN
say "LAB_BRIEF_DONE rc=${rc}"
exit "$rc"
