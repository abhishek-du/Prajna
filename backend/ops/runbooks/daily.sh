#!/usr/bin/env bash
# The Stage-1 daily incremental pipeline (besides the pre-open, which is
# ops/runbooks/preopen_day.sh).
#
#   ops/runbooks/daily.sh [--login] close   [YYYY-MM-DD]   # trading day, from 16:00 IST
#   ops/runbooks/daily.sh [--login] morning [YYYY-MM-DD]   # the NEXT morning, from 07:15 IST
#   ops/runbooks/daily.sh [--login] weekly                 # corporate actions
#   ops/runbooks/daily.sh [--login] monthly                # fundamentals (~42k requests)
#
# close    today's 1m / 15m / 1h bars for every NSE instrument (intraday
#          endpoint; only COMPLETE bars persist; ~10.6k requests), then news.
# morning  the session's daily bar for every NSE instrument (historical
#          endpoint, window = the 7 days up to the session so the checkpoint
#          stays contiguous across weekends and holidays; stored bars are
#          no-ops), FII/DII, news.
#
# Fail-closed: a step that fails is reported and the script exits non-zero;
# nothing is retried behind your back, and every job is resumable/idempotent.
# DAY defaults to today (IST) for close, and to the previous trading session
# (from trading_session) for morning.
# PRAJNA_UPSTOX_RATE_FRACTION is honoured (lower it when the B1/B2 poller or a
# backfill runs at the same time: the Upstox quota is per user).
set -euo pipefail

LOGIN=0
if [[ "${1:-}" == "--login" ]]; then LOGIN=1; shift; fi
PHASE="${1:?phase: close | morning | weekly | monthly}"
DAY="${2:-}"

cd "$(dirname "$0")/../.."
P=.venv/bin/python
CLI=("$P" -m app.cli.main --plain)
mkdir -p var/logs/daily
TODAY="$(TZ=Asia/Kolkata date +%F)"
LOG="var/logs/daily/${PHASE}_${DAY:-$TODAY}.log"
exec > >(tee -a "$LOG") 2>&1
TOKEN="$(grep '^PRAJNA_WRITE_TOKEN=' .env | cut -d= -f2-)"
say() { echo "[$(TZ=Asia/Kolkata date '+%F %T IST')] $*"; }
FAIL=0
run() {  # run <name> <cmd...>: log, keep going, remember failures
  local name="$1"; shift
  say "-> $name"
  if "$@" > "var/logs/daily/${PHASE}_${DAY:-$TODAY}_${name}.json"; then
    say "   $name OK"
  else
    say "   $name FAILED (exit $?) - see var/logs/daily/${PHASE}_${DAY:-$TODAY}_${name}.json"
    FAIL=1
  fi
}
sql1() { "${CLI[@]}" db sql "$1" | sed -n 3p | tr -d ' '; }

say "== daily $PHASE ${DAY:-}"

if ! "${CLI[@]}" upstox token-status | grep -q '"valid": true'; then
  if [[ $LOGIN -eq 1 ]]; then
    say "token invalid; --login given: performing TOTP login"
    "${CLI[@]}" upstox login
  else
    say "ABORT: Upstox token invalid (B0). Re-run with --login, or run 'upstox login' first."
    exit 3
  fi
fi

case "$PHASE" in
  close)
    DAY="${DAY:-$TODAY}"
    OPEN="$(sql1 "select is_trading_day from trading_session where session_date='${DAY}'")"
    if [[ "$OPEN" != "True" ]]; then say "SKIP: ${DAY} is not a recorded trading day ('${OPEN}')"; exit 0; fi
    if [[ "$DAY" == "$TODAY" && "$(TZ=Asia/Kolkata date +%H%M)" < "1600" ]]; then
      say "ABORT: run 'close' after 16:00 IST (bars still forming)"; exit 2
    fi
    run intraday "${CLI[@]}" ingest candles --timeframe 1m --timeframe 15m --timeframe 1h \
      --intraday --all-instruments --commit --token "$TOKEN"
    run news "${CLI[@]}" ingest news --commit --token "$TOKEN"
    ;;
  morning)
    if [[ -z "$DAY" ]]; then
      DAY="$(sql1 "select max(session_date) from trading_session where is_trading_day and session_date < '${TODAY}'")"
    fi
    FROM="$(TZ=Asia/Kolkata date -d "${DAY} -7 days" +%F)"
    run daily_1d "${CLI[@]}" ingest candles --timeframe 1d --from "$FROM" --to "$DAY" \
      --all-instruments --commit --token "$TOKEN"
    run fii_dii "${CLI[@]}" ingest institutional --commit --token "$TOKEN"
    run news "${CLI[@]}" ingest news --commit --token "$TOKEN"
    ;;
  weekly)
    run corporate_actions "${CLI[@]}" ingest corporate-actions --commit --token "$TOKEN"
    ;;
  monthly)
    run fundamentals "${CLI[@]}" ingest fundamentals --commit --token "$TOKEN"
    ;;
  *) say "unknown phase $PHASE"; exit 2 ;;
esac

say "done: $PHASE ${DAY:-} fail=${FAIL}"
exit $FAIL
