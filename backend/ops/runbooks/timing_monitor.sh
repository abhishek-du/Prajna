#!/usr/bin/env bash
# Timing-finality monitor (decision TIMING-B2, 2026-09-25). Read-only for the
# database; every vendor response is archived by the poller.
#
#   ops/runbooks/timing_monitor.sh
#
# Runs ops/measure/candle_timing.py (B2: intraday bars polled through the
# session; B1: historical daily bars through the night) until 09:10 IST the
# next day, then ops/measure/analyze_timing.py, which rewrites
# var/acceptance/b1b2.json - the evidence acceptance criterion X reads.
# The completion margin (contracts/timing.py, 120 s per in-scope timeframe) is
# an engineering threshold: any revision later than it is a LATE revision,
# reported here (TIMING_LATE_REVISION_DETECTED) and in X (BLOCKED, contract
# review). The margin is never enlarged automatically.
#
# Never two pollers: skips when one is already running. No login (an expired
# Upstox token pauses the poller until the morning jobs log in); no Prajna
# write token (nothing is written to the database).
# Rate: PRAJNA_UPSTOX_RATE_FRACTION 0.55 (beside the close 0.35, or the news
# poll 0.2, the per-user sum stays <= 0.9); in session this caps the poller
# slightly below its 6 s 1m cadence - the measurement stays valid, coarser.
# Markers: TIMING_MONITOR_STARTED / SKIPPED / COMPLETED, TIMING_LATE_REVISION_DETECTED.
set -uo pipefail
cd "$(dirname "$0")/../.."
P=.venv/bin/python
KEYS=("NSE_EQ|INE002A01018" "NSE_EQ|INE040A01034" "NSE_INDEX|Nifty 50")
mkdir -p var/logs/daily
TODAY="$(TZ=Asia/Kolkata date +%F)"
exec > >(tee -a "var/logs/daily/timing_monitor_${TODAY}.log") 2>&1
say() { echo "[$(TZ=Asia/Kolkata date '+%F %T IST')] $*"; }

if pgrep -f "ops/measure/candle_timin[g].py" > /dev/null; then
  say "TIMING_MONITOR_SKIPPED reason=a poller is already running"; exit 0
fi
UNTIL="$(TZ=Asia/Kolkata date -d tomorrow +%F) 09:10"
say "TIMING_MONITOR_STARTED until=${UNTIL} keys=${#KEYS[@]}"
args=(); for k in "${KEYS[@]}"; do args+=(--key "$k"); done
LEFT=$(( $(TZ=Asia/Kolkata date -d "$UNTIL" +%s) - $(date +%s) + 600 ))
PRAJNA_UPSTOX_RATE_FRACTION="${PRAJNA_UPSTOX_RATE_FRACTION:-0.55}" \
  timeout -k 60 --signal=INT "$LEFT" "$P" ops/measure/candle_timing.py --until "$UNTIL" "${args[@]}"
prc=$?
"$P" ops/measure/analyze_timing.py > /dev/null
arc=$?
"$P" - <<'PYEOF' | while read -r line; do say "$line"; done
import json
try:
    d = json.load(open("var/acceptance/b1b2.json"))
except Exception as e:
    print(f"TIMING_MONITOR_COMPLETED unreadable_verdict={type(e).__name__}")
    raise SystemExit(0)
b1, b2 = d.get("B1", {}), d.get("B2", {})
head = {tf: v.get("headroom_s") for tf, v in (b2.get("per_timeframe") or {}).items()
        if v.get("in_scope")}
print(f"TIMING_MONITOR_COMPLETED B1={b1.get('status')} ({len(b1.get('sessions_agreeing', []))} "
      f"agreeing) B2={b2.get('status')} ({len(b2.get('sessions_agreeing', []))} agreeing) "
      f"headroom_s={head}")
late = b2.get("late_revisions") or []
if late:
    print(f"TIMING_LATE_REVISION_DETECTED count={len(late)} first={late[0]}")
PYEOF
say "TIMING_MONITOR_EXIT poller_rc=${prc} analyze_rc=${arc}"
exit $(( prc == 0 || prc == 124 ? arc : prc ))
