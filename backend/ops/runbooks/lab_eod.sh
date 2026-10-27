#!/usr/bin/env bash
# Strategy Lab end of day (user 2026-10-27): today's lab build after the close job has stored
# the 1m bars (the Buy List is graded as intraday trades on them), then the AI-written
# "did the picks make money" report to Telegram. PAPER research only; no order.
#
#   ops/runbooks/lab_eod.sh [--no-telegram]
#
# Cron (weekdays 16:50, after close_then_backfill.sh at 16:05):
#   50 16 * * 1-5  cd $B && ops/runbooks/lab_eod.sh >> var/logs/cron.log 2>&1
set -uo pipefail
cd "$(dirname "$0")/../.."
P="${PRAJNA_PY:-.venv/bin/python}"
NOTIFY="${PRAJNA_TELEGRAM_CMD:-ops/runbooks/telegram_notify.sh}"
SEND=1; [[ "${1:-}" == "--no-telegram" ]] && SEND=0
mkdir -p var/logs/lab var/run
DAY="$(TZ=Asia/Kolkata date +%F)"; OUT="var/logs/lab/eod_${DAY}.json"
say() { echo "[$(TZ=Asia/Kolkata date '+%F %T IST')] $*"; }
exec 9> var/run/lab.lock
flock -w 600 9 || { say "LAB_EOD_SKIP another lab job holds var/run/lab.lock"; exit 0; }
export PRAJNA_SUPPLIED_TOKEN="$(grep '^PRAJNA_WRITE_TOKEN=' .env 2>/dev/null | cut -d= -f2-)"
say "LAB_EOD_START"
if "$P" -m app.cli.main --plain lab daily --session "$DAY" --commit > "$OUT" 2>&1; then
  rc=0; say "LAB_EOD_OK $(grep -o '"status": "[A-Z_]*"' "$OUT" | head -1)"
  if (( SEND )); then
    AWS_BEARER_TOKEN_BEDROCK="$(grep '^AWS_BEARER_TOKEN_BEDROCK=' .env 2>/dev/null | cut -d= -f2-)"
    export AWS_BEARER_TOKEN_BEDROCK
    msg="$("$P" -m app.lab.telegram_ai EOD "$DAY" 2>/dev/null)"
    unset AWS_BEARER_TOKEN_BEDROCK
    if [[ -n "$msg" ]]; then "$NOTIFY" "$msg" >/dev/null 2>&1 && say "LAB_EOD_TELEGRAM sent"; fi
  fi
else
  rc=1; why="$(grep -m1 REFUSED "$OUT" | cut -c1-300)"
  say "LAB_EOD_ALERT ${why:-failed (see ${OUT})}"
  (( SEND )) && "$NOTIFY" "Prajna Strategy Lab EOD ISSUE: ${why:-failed}" >/dev/null 2>&1
fi
unset PRAJNA_SUPPLIED_TOKEN
say "LAB_EOD_DONE rc=${rc}"
exit "$rc"
