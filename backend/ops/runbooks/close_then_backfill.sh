#!/usr/bin/env bash
# The daily close, then the approved intraday backfill, under ONE hold of the
# candles lock (the cron entry takes the flock; this script never runs two
# candle jobs at once, and nothing else can take the lock in between).
#
#   ops/runbooks/close_then_backfill.sh [--until HH:MM] [--no-backfill]
#
# --no-backfill (hardening phase 4; the live cron uses it while the historical
# backfill is DEFERRED_FOR_STAGE_1): close + rerun check only, no handoff.
#
# Why: the close (~10.6k requests at fraction 0.35) holds the lock for ~7.5 h,
# longer than a separate 19:45 backfill could wait for it, so on weekdays the
# backfill never started. Here it starts as soon as the close has completed.
#
#   1 CLOSE_STARTED    ops/runbooks/daily.sh --login close   (fraction 0.35)
#   2 CLOSE_COMPLETED  verdict: the backfill starts only when the close ran
#                      through: exit 0 (incl. SKIP on a non-trading day), or
#                      exit 1 whose intraday step was not stopped (no 429/auth
#                      abort, nothing aborted or left unattempted) - i.e. only
#                      per-instrument vendor failures, which are reported.
#                      Anything else (token, too early, aborted): no backfill.
#   3 CLOSE_RERUN_CHECK the same-day intraday rerun of 3 fixed instruments
#                      x 1m/15m/1h (9 requests): evidence that a second run
#                      inserts nothing (idempotency). Reported, never blocking.
#   4 BACKFILL_*       ops/runbooks/backfill.sh --login --until  (fraction 0.5)
#                      resumable from the stream checkpoints; logs
#                      BACKFILL_STARTED / BACKFILL_PROGRESS / BACKFILL_COMPLETED
#
# Failure classes (CLOSE_COMPLETED failure_class=...), so a token problem, a
# quota problem and a single bad instrument are never confused:
#   SUCCESS / SINGLE_INSTRUMENT_VENDOR_FAILURE (per-key vendor errors; ran through)
#   TOKEN_FAILURE (token invalid, or VendorAuthError stopped the close)
#   QUOTA_FAILURE (RateLimited stopped the close)
#   TOO_EARLY (before 16:00) / ABORTED (anything else that stopped it, including an
#   empty, truncated or missing intraday report: a hard stop kills the step mid-write)
# DATA_ABSENT windows (EMPTY) are counted, never a failure.
# Overrun guard: no handoff to the backfill between 06:50 and 16:00 IST.
#
# Scope, depth and rate fractions are unchanged: this only sequences the two
# existing runbooks. Test hooks: PRAJNA_RUNBOOK_DIR, PRAJNA_PY, PRAJNA_CLI,
# PRAJNA_TEST_NOW_HHMM.
set -uo pipefail

UNTIL="06:50"; NO_BACKFILL=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --until) UNTIL="$2"; shift 2 ;;
    --no-backfill) NO_BACKFILL=1; shift ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
done

cd "$(dirname "$0")/../.."
RB="${PRAJNA_RUNBOOK_DIR:-ops/runbooks}"
PY="${PRAJNA_PY:-.venv/bin/python}"
read -r -a CLI <<< "${PRAJNA_CLI:-.venv/bin/python -m app.cli.main --plain}"
CLOSE_FRACTION="${PRAJNA_CLOSE_FRACTION:-0.35}"
BACKFILL_FRACTION="${PRAJNA_BACKFILL_FRACTION:-0.5}"
RERUN_KEYS=("NSE_EQ|INE002A01018" "NSE_EQ|INE040A01034" "NSE_INDEX|Nifty 50")
mkdir -p var/logs/daily
TODAY="$(TZ=Asia/Kolkata date +%F)"
exec > >(tee -a "var/logs/daily/close_then_backfill_${TODAY}.log") 2>&1
say() { echo "[$(TZ=Asia/Kolkata date '+%F %T IST')] $*"; }

say "CLOSE_STARTED day=${TODAY} fraction=${CLOSE_FRACTION}"
PRAJNA_UPSTOX_RATE_FRACTION="$CLOSE_FRACTION" "$RB/daily.sh" --login close
rc=$?
J="var/logs/daily/close_${TODAY}_intraday.json"
verdict="not_completed"; fclass="ABORTED"; detail=""
case $rc in
  0) verdict="completed"; fclass="SUCCESS" ;;
  2) fclass="TOO_EARLY" ;;
  3) fclass="TOKEN_FAILURE" ;;
esac
if [[ -f "$J" && ( $rc -eq 0 || $rc -eq 1 ) ]]; then
  # the intraday step's own report decides: ran through, or stopped - and why
  detail="$("$PY" - "$J" <<'EOF'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    assert isinstance(d, dict)
except Exception as e:                  # interrupted mid-write: never "ran through"
    print(f"stopped ABORTED unreadable_report={type(e).__name__}")
    raise SystemExit(0)
stopped = d.get("stopped") or ""
ran = not stopped and not d.get("aborted") and not d.get("not_attempted")
if ran:
    cls = "SINGLE_INSTRUMENT_VENDOR_FAILURE" if d.get("failed") else "SUCCESS"
elif stopped.startswith("VendorAuthError"):
    cls = "TOKEN_FAILURE"
elif stopped.startswith("RateLimited"):
    cls = "QUOTA_FAILURE"
else:
    cls = "ABORTED"
empty = (d.get("coverage") or {}).get("EMPTY", 0)
print(f"{'ran' if ran else 'stopped'} {cls} complete={d.get('complete')} "
      f"failed={d.get('failed')} aborted={d.get('aborted')} "
      f"not_attempted={d.get('not_attempted')} data_absent={empty}")
EOF
)"
  fclass="$(cut -d' ' -f2 <<<"$detail")"
  [[ -z "$fclass" ]] && fclass="ABORTED"   # the verdict helper itself failed
  if [[ "$detail" == ran* ]]; then
    [[ "$fclass" == "SUCCESS" ]] && verdict="completed" || verdict="completed_with_instrument_failures"
  else
    verdict="not_completed"
  fi
fi
say "CLOSE_COMPLETED rc=${rc} verdict=${verdict} failure_class=${fclass} ${detail#* * }"

if [[ "$verdict" == "not_completed" ]]; then
  say "BACKFILL_SKIPPED reason=close_not_completed (rc=${rc}); the next scheduled run resumes"
  exit "$rc"
fi

if [[ -f "$J" ]]; then                  # a trading day: the same-day rerun check
  # the write token travels in the environment, never in argv (visible to ps)
  export PRAJNA_SUPPLIED_TOKEN="$(grep '^PRAJNA_WRITE_TOKEN=' .env | cut -d= -f2-)"
  args=(); for k in "${RERUN_KEYS[@]}"; do args+=(--key "$k"); done
  R="var/logs/daily/close_${TODAY}_rerun_check.json"
  PRAJNA_UPSTOX_RATE_FRACTION="$CLOSE_FRACTION" "${CLI[@]}" ingest candles --timeframe 1m \
    --timeframe 15m --timeframe 1h --intraday "${args[@]}" --commit > "$R"
  "$PY" - "$R" <<'EOF' | while read -r line; do say "CLOSE_RERUN_CHECK $line"; done
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    print(f"jobs={d.get('jobs')} complete={d.get('complete')} inserted={d.get('inserted')} "
          f"failed={len(d.get('failed') or [])} idempotent={d.get('inserted') == 0}")
except Exception as e:                  # reported, never blocking
    print(f"unreadable: {e!r}")
EOF
fi

if [[ $NO_BACKFILL -eq 1 ]]; then
  say "BACKFILL_DEFERRED reason=DEFERRED_FOR_STAGE_1 (--no-backfill)"
  exit 0
fi
hhmm="${PRAJNA_TEST_NOW_HHMM:-$(TZ=Asia/Kolkata date +%H%M)}"
if [[ ! "$hhmm" < "0650" && "$hhmm" < "1600" ]]; then
  say "BACKFILL_SKIPPED reason=overrun_guard (${hhmm} IST is inside 06:50-16:00)"
  exit 0
fi
say "handing over to the backfill (same lock hold) until ${UNTIL} IST"
PRAJNA_UPSTOX_RATE_FRACTION="$BACKFILL_FRACTION" "$RB/backfill.sh" --login --until "$UNTIL"
brc=$?
exit "$brc"
