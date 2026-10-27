#!/usr/bin/env bash
# Research Desk run (user 2026-10-27; docs/RESEARCH_DESK.md): dossiers, the LLM
# investigation (Nova Pro on AWS Bedrock), verdicts and the auto-managed watchlist.
# PAPER ONLY: suggestions, never orders.
#
#   ops/runbooks/desk_run.sh EVENING|MORNING|INTRADAY [--no-telegram]
#
# Cron (Mon-Fri): 19:45 EVENING (every liquid stock), 08:40 MORNING (overnight changes),
# 11:00 and 13:30 INTRADAY (the watchlist and the largest live movers)
#   45 19 * * 1-5  cd $B && ops/runbooks/desk_run.sh EVENING >> var/logs/cron.log 2>&1
#   40 8 * * 1-5   cd $B && ops/runbooks/desk_run.sh MORNING >> var/logs/cron.log 2>&1
#   0 11 * * 1-5   cd $B && ops/runbooks/desk_run.sh INTRADAY >> var/logs/cron.log 2>&1
#   30 13 * * 1-5  cd $B && ops/runbooks/desk_run.sh INTRADAY >> var/logs/cron.log 2>&1
# The Bedrock API key is read from .env (AWS_BEARER_TOKEN_BEDROCK) into the environment
# only: never argv, never printed.
set -uo pipefail
cd "$(dirname "$0")/../.."
P="${PRAJNA_PY:-.venv/bin/python}"
NOTIFY="${PRAJNA_TELEGRAM_CMD:-ops/runbooks/telegram_notify.sh}"
MODE="${1:-EVENING}"; SEND=1; [[ "${2:-}" == "--no-telegram" ]] && SEND=0
mkdir -p var/logs/desk var/run
STAMP="$(TZ=Asia/Kolkata date +%F_%H%M)"; OUT="var/logs/desk/${MODE,,}_${STAMP}.json"
ERR="var/logs/desk/${MODE,,}_${STAMP}.err"
say() { echo "[$(TZ=Asia/Kolkata date '+%F %T IST')] $*"; }
exec 9> var/run/desk.lock
flock -n 9 || { say "DESK_SKIP another desk run holds var/run/desk.lock"; exit 0; }
AWS_BEARER_TOKEN_BEDROCK="$(grep '^AWS_BEARER_TOKEN_BEDROCK=' .env 2>/dev/null | cut -d= -f2-)"
[[ -z "$AWS_BEARER_TOKEN_BEDROCK" ]] && { say "DESK_SKIP no Bedrock key in .env"; exit 0; }
export AWS_BEARER_TOKEN_BEDROCK
export PRAJNA_SUPPLIED_TOKEN="$(grep '^PRAJNA_WRITE_TOKEN=' .env 2>/dev/null | cut -d= -f2-)"
say "DESK_START ${MODE}"
if "$P" -m app.cli.main --plain desk run --mode "$MODE" --commit > "$OUT" 2> "$ERR"; then
  rc=0
  say "DESK_OK ${MODE} $(tr -d '\n ' < "$OUT" | grep -o '"mix":{[^}]*}' | head -1)"
  if (( SEND )); then
    msg="$("$P" -m app.desk.summary "$OUT" 2>/dev/null)"
    [[ -n "$msg" ]] && "$NOTIFY" "$msg" >/dev/null 2>&1
  fi
else
  rc=1; why="$(grep -m1 REFUSED "$OUT" | cut -c1-300)"
  say "DESK_ALERT ${MODE} ${why:-failed (see ${OUT})}"
  (( SEND )) && "$NOTIFY" "Prajna Research Desk ISSUE (${MODE}): ${why:-failed}" >/dev/null 2>&1
fi
unset PRAJNA_SUPPLIED_TOKEN AWS_BEARER_TOKEN_BEDROCK
say "DESK_DONE ${MODE} rc=${rc}"
exit "$rc"
