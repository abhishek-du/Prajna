#!/usr/bin/env bash
# The real-trading-day pre-open acceptance run (Stage 1, criteria H and L).
#
#   ops/runbooks/preopen_day.sh [--login] [YYYY-MM-DD]
#
# Every step is fail-closed; nothing is retried behind your back.
#   1. calendar   the day must be a recorded trading day with a pre-open window
#   2. token      probe the cached Upstox token; only with --login is a TOTP
#                 login performed (a REAL login to the live account)
#   3. universe   download the public instrument master, commit the universe
#   4. capture    wait until 08:55 IST, then record every connection to 09:20
#   5. replay     commit every connection archive
#   6. acceptance grade the day; the report lands in var/acceptance/
#
# Start it any time before 08:50 IST. Everything is logged to
# var/logs/preopen_<day>.log.
set -euo pipefail

LOGIN=0
if [[ "${1:-}" == "--login" ]]; then LOGIN=1; shift; fi
DAY="${1:-$(TZ=Asia/Kolkata date +%F)}"

cd "$(dirname "$0")/../.."
P=.venv/bin/python
CLI=("$P" -m app.cli.main --plain)
mkdir -p var/logs var/acceptance
LOG="var/logs/preopen_${DAY}.log"
exec > >(tee -a "$LOG") 2>&1
TOKEN="$(grep '^PRAJNA_WRITE_TOKEN=' .env | cut -d= -f2-)"
say() { echo "[$(TZ=Asia/Kolkata date '+%F %T IST')] $*"; }

say "== pre-open acceptance day $DAY"

say "1/6 calendar"
ROW="$("${CLI[@]}" db sql "select is_trading_day, preopen_start_ist from trading_session where session_date='${DAY}'" | sed -n 3p)"
if [[ "$ROW" != True* ]] || [[ "$ROW" == *"·"* ]]; then
  say "ABORT: ${DAY} is not a recorded trading day with a pre-open window: '${ROW}'"
  say "       run: ingest calendar --from ${DAY} --to ${DAY} --commit"
  exit 2
fi

say "2/6 token"
if ! "${CLI[@]}" upstox token-status | grep -q '"valid": true'; then
  if [[ $LOGIN -eq 1 ]]; then
    say "token invalid; --login given: performing TOTP login"
    "${CLI[@]}" upstox login
  else
    say "ABORT: Upstox token invalid (B0). Re-run with --login, or run 'upstox login' first."
    exit 3
  fi
fi

say "3/6 universe"
"${CLI[@]}" ingest universe --download --session-date "$DAY" --commit --token "$TOKEN" \
  --keys-out "var/logs/universe_${DAY}.txt" | tee "var/logs/universe_${DAY}.json" >/dev/null
grep -q '"status": "COMPLETE"' "var/logs/universe_${DAY}.json" || { say "ABORT: universe"; exit 4; }

say "4/6 capture (waiting for 08:55 IST)"
while [[ "$(TZ=Asia/Kolkata date +%H%M)" < "0855" ]]; do sleep 20; done
set +e
"${CLI[@]}" ingest preopen-capture --universe-date "$DAY" --session-date "$DAY" \
  --until 09:20 --connections 2 --per-connection 2000 --stale-after 60 \
  > "var/logs/capture_${DAY}.json"
CAP=$?
set -e
MANIFEST="$("$P" -c "import json,sys; print(json.load(open(sys.argv[1]))['manifest'])" \
  "var/logs/capture_${DAY}.json")"
say "capture exit ${CAP}; manifest ${MANIFEST}"

say "5/6 replay"
set +e
"${CLI[@]}" ingest preopen --replay-from-session "$MANIFEST" --commit --token "$TOKEN" \
  > "var/logs/replay_${DAY}.json"
REP=$?
set -e
say "replay exit ${REP}"

say "6/6 acceptance"
set +e
"${CLI[@]}" acceptance preopen --session "$MANIFEST" --out "var/acceptance/preopen_${DAY}.json" \
  > /dev/null
ACC=$?
set -e
"$P" - "var/acceptance/preopen_${DAY}.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
print(f"verdict {d['verdict']}  real={d['real_market_data']}  window={d['preopen_window_ist']}")
for c in d["checks"]:
    print(f"  {c['id']:3} {c['status']:10} {c['requirement']}")
print("  B7", d["B7"].get("status"), "| B8", d["B8"].get("status"))
PY
say "done: capture=${CAP} replay=${REP} acceptance=${ACC}"
exit $(( CAP || REP || ACC ))
