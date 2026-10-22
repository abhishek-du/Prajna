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
#   5. replay     commit every connection archive. With PREOPEN-TAIL (user
#                 2026-10-22) a tailing replay runs DURING the capture: every 10 s each
#                 connection's new records are committed (same replay code, one run per
#                 pass); after the first pass at PRE_OPEN as_of + 5 s it writes
#                 var/run/preopen_ready_<day>.json for Stage 3 PRE_OPEN (--after-tail).
#                 It ends when the archives are closed and verified. A failed tail falls
#                 back to the full replay (idempotent). OFF until its full-rate rehearsal
#                 has passed (2026-10-22): PRAJNA_PREOPEN_TAIL=1 enables it.
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
# the write token travels in the environment, never in argv (visible to ps)
export PRAJNA_SUPPLIED_TOKEN="$(grep '^PRAJNA_WRITE_TOKEN=' .env | cut -d= -f2-)"
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
"${CLI[@]}" ingest universe --download --session-date "$DAY" --commit \
  --keys-out "var/logs/universe_${DAY}.txt" | tee "var/logs/universe_${DAY}.json" >/dev/null
grep -q '"status": "COMPLETE"' "var/logs/universe_${DAY}.json" || { say "ABORT: universe"; exit 4; }

say "4/6 capture (waiting for 08:55 IST)"
while [[ "$(TZ=Asia/Kolkata date +%H%M)" < "0855" ]]; do sleep 20; done
set +e
CERR="var/logs/capture_${DAY}.err"
: > "$CERR"
"${CLI[@]}" ingest preopen-capture --universe-date "$DAY" --session-date "$DAY" \
  --until 09:20 --connections 2 --per-connection 2000 --stale-after 60 \
  > "var/logs/capture_${DAY}.json" 2> "$CERR" &
CPID=$!
TPID=""
if [[ "${PRAJNA_PREOPEN_TAIL:-0}" == 1 ]]; then
  # the capture names its session manifest on stderr as soon as it has written it
  for _ in $(seq 1 60); do
    grep -q "^session manifest: " "$CERR" && break
    kill -0 "$CPID" 2>/dev/null || break
    sleep 1
  done
  TMAN="$(grep -m1 "^session manifest: " "$CERR" | cut -d' ' -f3-)"
  if [[ -n "$TMAN" ]]; then
    "${CLI[@]}" ingest preopen-tail --manifest "$TMAN" --commit \
      > "var/logs/tail_${DAY}.json" 2> "var/logs/tail_${DAY}.err" &
    TPID=$!
    say "tail started (pid ${TPID}) on ${TMAN}"
  else
    say "tail NOT started: no session manifest from the capture; full replay after it"
  fi
fi
wait "$CPID"
CAP=$?
cat "$CERR"
set -e
MANIFEST="$("$P" -c "import json,sys; print(json.load(open(sys.argv[1]))['manifest'])" \
  "var/logs/capture_${DAY}.json")"
say "capture exit ${CAP}; manifest ${MANIFEST}"

say "5/6 replay"
set +e
REP=1
if [[ -n "$TPID" ]]; then
  wait "$TPID"
  REP=$?
  say "tail exit ${REP}: $("$P" - "var/logs/tail_${DAY}.json" 2>/dev/null <<'PY' || echo "output unreadable"
import json, sys
d = json.load(open(sys.argv[1]))
r = d.get("ready") or {}
print(f"status={d.get('status')} passes={d.get('passes')} ready_pass={r.get('pass_started_at')} "
      f"late_ticks={d.get('late_ticks')} error={d.get('error')}")
PY
)"
fi
if [[ $REP -ne 0 ]]; then
  "${CLI[@]}" ingest preopen --replay-from-session "$MANIFEST" --commit \
    > "var/logs/replay_${DAY}.json"
  REP=$?
fi
if [[ $REP -eq 0 ]]; then
  # Fresh planner statistics for today's rows BEFORE the "replay exit" line, which
  # stage3_snapshot.sh --after-replay waits for. A session that adds < 10% of the
  # table (the autoanalyze threshold) is otherwise estimated at 1 row, and PRE_OPEN's
  # per-instrument query scans the whole day (2026-10-13: 842 s instead of ~260 s).
  # Best effort: a failure or timeout is logged and changes nothing else.
  timeout 300 "$P" - <<'PY'
import asyncio, time
from sqlalchemy import text
from app.db.engine import get_sessionmaker
async def go():
    async with get_sessionmaker()() as s:
        await s.execute(text("set local lock_timeout = '30s'"))
        await s.execute(text("set local statement_timeout = '240s'"))
        t = time.monotonic()
        await s.execute(text("analyze preopen_tick, preopen_book"))
        await s.commit()
        print(f"ANALYZE_PREOPEN OK seconds={time.monotonic() - t:.2f}")
asyncio.run(go())
PY
  say "analyze_preopen exit $?"
fi
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
