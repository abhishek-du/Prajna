#!/usr/bin/env bash
# Strategy Lab daily build (user 2026-10-27; docs/STRATEGY_LAB.md): per-day strategy
# performance, trade and day forensics for the finished sessions (the last 7 plus any
# session without a lab run), then a Telegram summary of the latest session. PAPER/SHADOW
# research only: it reads the P1, paper, E5 and E6 records and writes only the lab tables.
#
#   ops/runbooks/lab_daily.sh [--no-telegram]
#
# Cron (weekdays): 15:55 (after paper_daily.sh 15:40) and 22:45 (after shadow_review.sh 22:15)
#   55 15 * * 1-5  cd $B && ops/runbooks/lab_daily.sh --no-telegram >> var/logs/cron.log 2>&1
#   45 22 * * 1-5  cd $B && ops/runbooks/lab_daily.sh >> var/logs/cron.log 2>&1
set -uo pipefail
cd "$(dirname "$0")/../.."
P="${PRAJNA_PY:-.venv/bin/python}"
NOTIFY="${PRAJNA_TELEGRAM_CMD:-ops/runbooks/telegram_notify.sh}"
SEND=1; [[ "${1:-}" == "--no-telegram" ]] && SEND=0
mkdir -p var/logs/lab var/run
DAY="$(TZ=Asia/Kolkata date +%F)"; OUT="var/logs/lab/daily_${DAY}_$(TZ=Asia/Kolkata date +%H%M).json"
say() { echo "[$(TZ=Asia/Kolkata date '+%F %T IST')] $*"; }
exec 9> var/run/lab.lock
flock -n 9 || { say "LAB_DAILY_SKIP another lab job holds var/run/lab.lock"; exit 0; }
export PRAJNA_SUPPLIED_TOKEN="$(grep '^PRAJNA_WRITE_TOKEN=' .env 2>/dev/null | cut -d= -f2-)"
# after the 16:05 close job stored today's 1m bars, today is a finished session too: its daily
# bar only lands with the next morning's job, so without --to the 22:45 build stopped at the
# previous session and P1/P2 showed a day late (seen 2026-10-27)
TO=(); [[ "$(TZ=Asia/Kolkata date +%H%M)" > "1630" ]] && TO=(--to "$DAY")
say "LAB_DAILY_START ${TO[*]}"
if "$P" -m app.cli.main --plain lab daily "${TO[@]}" --commit > "$OUT" 2>&1; then
  rc=0
  say "LAB_DAILY_OK $(grep -o '"status": "[A-Z_]*"' "$OUT" | sort | uniq -c | tr -s ' ' | tr '\n' ';')"
  if (( SEND )); then
    msg="$("$P" -m app.lab.summary 2>/dev/null)"
    [[ -n "$msg" ]] && "$NOTIFY" "$msg" >/dev/null 2>&1
  fi
else
  rc=1; why="$(grep -m1 REFUSED "$OUT" | cut -c1-300)"
  say "LAB_DAILY_ALERT ${why:-failed (see ${OUT})}"
  (( SEND )) && "$NOTIFY" "Prajna Strategy Lab ISSUE: ${why:-failed}" >/dev/null 2>&1
fi
unset PRAJNA_SUPPLIED_TOKEN
say "LAB_DAILY_DONE rc=${rc}"
exit "$rc"
