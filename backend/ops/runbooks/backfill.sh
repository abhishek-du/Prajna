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
# the candles quota with the daily close/morning runs; on weekdays
# ops/runbooks/close_then_backfill.sh starts it right after the close.
# Log markers: BACKFILL_STARTED, BACKFILL_PROGRESS (per stage, and every 30 min
# during a stage: instruments whose checkpoint reaches the depth), and
# BACKFILL_COMPLETED rc=.. status=.. on every exit.
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
STATUS="started"
TICK=""
finish() {
  local rc=$?
  [[ -n "$TICK" ]] && { pkill -P "$TICK" 2>/dev/null; kill "$TICK" 2>/dev/null; }
  say "BACKFILL_COMPLETED rc=${rc} status=${STATUS}"
}
trap finish EXIT
progress() {  # progress <tf> <from>: instruments whose checkpoint reaches the depth
  local n
  n="$("${CLI[@]}" db sql "select count(*) filter (where (r.request_params->'outcome'->'checkpoint'->>'covered_from')::date <= '$2'), count(*) from instrument i left join ingest_watermark w on w.source='UPSTOX_REST_V3' and w.stream='ohlcv.$1.'||i.instrument_key left join ingest_run r on r.run_id=w.last_run_id where i.valid_to='infinity' and i.segment in ('NSE_EQ','NSE_INDEX')" 2>/dev/null | sed -n 3p | awk '{print $1 "/" $2}')" || true
  say "BACKFILL_PROGRESS tf=$1 from=$2 covered=${n:-unknown}"
}

# seconds until the next UNTIL (today or tomorrow), IST
now_s=$(TZ=Asia/Kolkata date +%s)
stop_s=$(TZ=Asia/Kolkata date -d "today ${UNTIL}" +%s)
(( stop_s <= now_s )) && stop_s=$(TZ=Asia/Kolkata date -d "tomorrow ${UNTIL}" +%s)
say "== backfill until ${UNTIL} IST ($(( (stop_s - now_s) / 60 )) min)"
say "BACKFILL_STARTED until=${UNTIL} fraction=${PRAJNA_UPSTOX_RATE_FRACTION:-default}"
if pgrep -f "app.cli.main.* ingest candles" > /dev/null; then
  STATUS="another_candles_job_running"
  say "another candles job is running; not starting (the quota is per user)"; exit 0
fi

if ! "${CLI[@]}" upstox token-status | grep -q '"valid": true'; then
  if [[ $LOGIN -eq 1 ]]; then say "token invalid; --login: TOTP login"; "${CLI[@]}" upstox login
  else STATUS="token_invalid"; say "ABORT: token invalid"; exit 3; fi
fi

TODAY="$(TZ=Asia/Kolkata date +%F)"
LAST="$("${CLI[@]}" db sql "select max(session_date) from trading_session where is_trading_day and session_date < '${TODAY}'" | sed -n 3p | tr -d ' ')"
SIX="$(TZ=Asia/Kolkata date -d "${TODAY} -183 days" +%F)"
STAGES=("1h 2022-01-01" "1m ${SIX}" "15m 2022-01-01")

for st in "${STAGES[@]}"; do
  set -- $st; TF=$1; FROM=$2
  free_gb=$(df -BG --output=avail / | tail -1 | tr -dc 0-9)
  if (( free_gb < 60 )); then STATUS="disk_low"; say "STOP: free disk ${free_gb} GB < 60 GB"; exit 5; fi
  left=$(( stop_s - $(TZ=Asia/Kolkata date +%s) ))
  if (( left < 120 )); then STATUS="time_window_over"; say "time window over"; exit 0; fi
  progress "$TF" "$FROM"
  say "-> ${TF} ${FROM} .. ${LAST} (${left}s left)"
  ( while sleep 1800; do progress "$TF" "$FROM"; done ) &
  TICK=$!
  set +e
  timeout --signal=INT "${left}" "${CLI[@]}" ingest candles --timeframe "$TF" --from "$FROM" \
    --to "$LAST" --all-instruments --commit --token "$TOKEN" \
    > "var/logs/backfill/${TF}_${STAMP}.json"
  rc=$?
  pkill -P "$TICK" 2>/dev/null; kill "$TICK" 2>/dev/null; TICK=""
  set -e
  say "   ${TF} exit ${rc}"
  progress "$TF" "$FROM"
  case $rc in
    0) ;;                                  # stage complete -> next stage
    124|130) STATUS="time_limit_resumable"; say "stopped at the time limit (resumable)"; exit 0 ;;
    *) "$P" -c "import json,sys; d=json.load(open(sys.argv[1])); print('   stopped:', d.get('stopped'), '| failed:', len(d.get('failed',[])))" \
         "var/logs/backfill/${TF}_${STAMP}.json" 2>/dev/null || true
       STATUS="stage_${TF}_not_complete"
       say "stage ${TF} not complete (see log); stopping, resumable"; exit "$rc" ;;
  esac
done
STATUS="all_stages_complete"
say "all stages complete to the approved depth"
