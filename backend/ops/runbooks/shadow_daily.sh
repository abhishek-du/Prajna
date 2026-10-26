#!/usr/bin/env bash
# Stage 4 v2 P1 shadow job (docs/STAGE4_P1_SHADOW_PREREGISTRATION.md): every session from
# the frozen policy's forward start whose 1d and 1m bars are stored, after the last
# recorded one. SHADOW ONLY: zero capital, no broker, no orders. Telegram on a refusal
# only; shadow P&L is never printed or sent (it is read at the pre-registered looks).
#
#   ops/runbooks/shadow_daily.sh [--no-telegram]
#
# Cron (weekdays 21:30 IST, after the 1m bars land ~19:00; session T runs once T's 1d bar
# is stored, i.e. on T + 1):
#   30 21 * * 1-5  cd $B && ops/runbooks/shadow_daily.sh >> var/logs/cron.log 2>&1
set -uo pipefail
cd "$(dirname "$0")/../.."
P="${PRAJNA_PY:-.venv/bin/python}"
NOTIFY="${PRAJNA_TELEGRAM_CMD:-ops/runbooks/telegram_notify.sh}"
SEND=1; [[ "${1:-}" == "--no-telegram" ]] && SEND=0
mkdir -p var/logs/shadow var/run
DAY="$(TZ=Asia/Kolkata date +%F)"; OUT="var/logs/shadow/daily_${DAY}.json"
say() { echo "[$(TZ=Asia/Kolkata date '+%F %T IST')] $*"; }
exec 9> var/run/shadow.lock
flock -n 9 || { say "SHADOW_DAILY_SKIP another shadow job holds var/run/shadow.lock"; exit 0; }
export PRAJNA_SUPPLIED_TOKEN="$(grep '^PRAJNA_WRITE_TOKEN=' .env 2>/dev/null | cut -d= -f2-)"
say "SHADOW_DAILY_START"
if "$P" -m app.cli.main --plain shadow daily --commit > "$OUT" 2>&1; then
  rc=0
  say "SHADOW_DAILY_OK $(grep -o '"status": "[A-Z_]*"' "$OUT" | sort | uniq -c | tr -s ' ' | tr '\n' ';')"
else
  rc=1; why="$(grep -m1 REFUSED "$OUT" | cut -c1-300)"
  say "SHADOW_DAILY_ALERT ${why:-failed (see ${OUT})}"
  (( SEND )) && "$NOTIFY" "Prajna SHADOW job ISSUE: ${why:-failed}" >/dev/null 2>&1
fi
unset PRAJNA_SUPPLIED_TOKEN
say "SHADOW_DAILY_DONE rc=${rc}"
exit "$rc"
