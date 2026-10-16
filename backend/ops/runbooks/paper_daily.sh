#!/usr/bin/env bash
# Stage 7-8 forward paper job (decision 2026-10-16 under the user's delegation): every
# session after each strategy's last recorded one, from 2026-10-16 (after the research
# TEST windows), then the PAPER report of the forward sessions only to Telegram. PAPER ONLY: no broker, no orders.
#
#   ops/runbooks/paper_daily.sh [--no-telegram]
#
# Cron (weekdays 15:40 IST, after the close; the previous session's 1d bars land ~08:32):
#   40 15 * * 1-5  cd $B && ops/runbooks/paper_daily.sh >> var/logs/cron.log 2>&1
# A refused strategy is a Telegram alert (PAPER_DAILY_ALERT); the others still run.
set -uo pipefail
cd "$(dirname "$0")/../.."
P="${PRAJNA_PY:-.venv/bin/python}"
NOTIFY="${PRAJNA_TELEGRAM_CMD:-ops/runbooks/telegram_notify.sh}"
STRATS="${PRAJNA_PAPER_STRATEGIES:-baseline_gap_fade,bench_c0}"
SEND=1; [[ "${1:-}" == "--no-telegram" ]] && SEND=0
mkdir -p var/logs/paper var/run
DAY="$(TZ=Asia/Kolkata date +%F)"; LOG="var/logs/paper/daily_${DAY}.log"
say() { echo "[$(TZ=Asia/Kolkata date '+%F %T IST')] $*" | tee -a "$LOG"; }
exec 9> var/run/paper.lock
flock -n 9 || { say "PAPER_DAILY_SKIP another paper job holds var/run/paper.lock"; exit 0; }
export PRAJNA_SUPPLIED_TOKEN="$(grep '^PRAJNA_WRITE_TOKEN=' .env 2>/dev/null | cut -d= -f2-)"
say "PAPER_DAILY_START strategies=${STRATS}"
rc=0
IFS=',' read -ra LIST <<< "$STRATS"
for st in "${LIST[@]}"; do
  out="var/logs/paper/daily_${DAY}_${st}.json"
  if "$P" -m app.cli.main --plain paper daily --strategy "$st" --commit > "$out" 2>&1; then
    say "PAPER_DAILY_OK ${st} $(grep -o '"status": "[A-Z_]*"' "$out" | sort | uniq -c | tr -s ' ' | tr '\n' ';')"
  else
    rc=1; why="$(grep -m1 REFUSED "$out" | cut -c1-300)"
    say "PAPER_DAILY_ALERT ${st} ${why:-failed (see ${out})}"
    (( SEND )) && "$NOTIFY" "Prajna PAPER job ISSUE: ${st}: ${why:-failed}" >/dev/null 2>&1
  fi
done
unset PRAJNA_SUPPLIED_TOKEN
if (( SEND )); then ops/runbooks/paper_report.sh --from 2026-10-16 --strategies "$STRATS" >> "$LOG" 2>&1 || rc=1
else ops/runbooks/paper_report.sh --from 2026-10-16 --strategies "$STRATS" --no-telegram >> "$LOG" 2>&1 || rc=1; fi
say "PAPER_DAILY_DONE rc=${rc}"
exit "$rc"
