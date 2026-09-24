#!/usr/bin/env bash
# Stage-1 intraday history backfill to the approved depth (decision D1):
#   1h since 2022-01, 1m for the last 6 months, 15m since 2022-01.
#
#   ops/runbooks/backfill.sh [--login] [--until HH:MM]
#
# Resumable and idempotent: every stage is `ingest candles --commit` with the
# stream checkpoints ([covered_from, through]); rerunning it continues where it
# stopped and re-stored bars are no-ops. It stops by itself at --until (IST,
# default 06:50: the morning daily run and the pre-open come next), on a
# 429/auth error (the ingest aborts cleanly), and when free disk < 60 GB.
# Run it under the candles lock (see ops/cron/prajna.cron) so it never shares
# the candles quota with the daily close/morning runs.
set -euo pipefail

LOGIN=0
if [[ "${1:-}" == "--login" ]]; then LOGIN=1; shift; fi
UNTIL="06:50"
if [[ "${1:-}" == "--until" ]]; then UNTIL="$2"; shift 2; fi

cd "$(dirname "$0")/../.."
P=.venv/bin/python
CLI=("$P" -m app.cli.main --plain)
mkdir -p var/logs/backfill
STAMP="$(TZ=Asia/Kolkata date +%F_%H%M)"
exec > >(tee -a "var/logs/backfill/backfill_${STAMP}.log") 2>&1
TOKEN="$(grep '^PRAJNA_WRITE_TOKEN=' .env | cut -d= -f2-)"
say() { echo "[$(TZ=Asia/Kolkata date '+%F %T IST')] $*"; }

# seconds until the next UNTIL (today or tomorrow), IST
now_s=$(TZ=Asia/Kolkata date +%s)
stop_s=$(TZ=Asia/Kolkata date -d "today ${UNTIL}" +%s)
(( stop_s <= now_s )) && stop_s=$(TZ=Asia/Kolkata date -d "tomorrow ${UNTIL}" +%s)
say "== backfill until ${UNTIL} IST ($(( (stop_s - now_s) / 60 )) min)"
if pgrep -f "app.cli.main.* ingest candles" > /dev/null; then
  say "another candles job is running; not starting (the quota is per user)"; exit 0
fi

if ! "${CLI[@]}" upstox token-status | grep -q '"valid": true'; then
  if [[ $LOGIN -eq 1 ]]; then say "token invalid; --login: TOTP login"; "${CLI[@]}" upstox login
  else say "ABORT: token invalid"; exit 3; fi
fi

TODAY="$(TZ=Asia/Kolkata date +%F)"
LAST="$("${CLI[@]}" db sql "select max(session_date) from trading_session where is_trading_day and session_date < '${TODAY}'" | sed -n 3p | tr -d ' ')"
SIX="$(TZ=Asia/Kolkata date -d "${TODAY} -183 days" +%F)"
STAGES=("1h 2022-01-01" "1m ${SIX}" "15m 2022-01-01")

for st in "${STAGES[@]}"; do
  set -- $st; TF=$1; FROM=$2
  free_gb=$(df -BG --output=avail / | tail -1 | tr -dc 0-9)
  if (( free_gb < 60 )); then say "STOP: free disk ${free_gb} GB < 60 GB"; exit 5; fi
  left=$(( stop_s - $(TZ=Asia/Kolkata date +%s) ))
  if (( left < 120 )); then say "time window over"; exit 0; fi
  say "-> ${TF} ${FROM} .. ${LAST} (${left}s left)"
  set +e
  timeout --signal=INT "${left}" "${CLI[@]}" ingest candles --timeframe "$TF" --from "$FROM" \
    --to "$LAST" --all-instruments --commit --token "$TOKEN" \
    > "var/logs/backfill/${TF}_${STAMP}.json"
  rc=$?
  set -e
  say "   ${TF} exit ${rc}"
  case $rc in
    0) ;;                                  # stage complete -> next stage
    124|130) say "stopped at the time limit (resumable)"; exit 0 ;;
    *) "$P" -c "import json,sys; d=json.load(open(sys.argv[1])); print('   stopped:', d.get('stopped'), '| failed:', len(d.get('failed',[])))" \
         "var/logs/backfill/${TF}_${STAMP}.json" 2>/dev/null || true
       say "stage ${TF} not complete (see log); stopping, resumable"; exit "$rc" ;;
  esac
done
say "all stages complete to the approved depth"
