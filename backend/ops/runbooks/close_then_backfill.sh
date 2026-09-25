#!/usr/bin/env bash
# The daily close, then the approved intraday backfill, under ONE hold of the
# candles lock (the cron entry takes the flock; this script never runs two
# candle jobs at once, and nothing else can take the lock in between).
#
#   ops/runbooks/close_then_backfill.sh [--until HH:MM]      # default 06:50
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
# Scope, depth and rate fractions are unchanged: this only sequences the two
# existing runbooks. Test hooks: PRAJNA_RUNBOOK_DIR, PRAJNA_PY, PRAJNA_CLI.
set -uo pipefail

UNTIL="06:50"
if [[ "${1:-}" == "--until" ]]; then UNTIL="$2"; shift 2; fi

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
verdict="not_completed"
if [[ $rc -eq 0 ]]; then
  verdict="completed"
elif [[ $rc -eq 1 && -f "$J" ]]; then
  # completed with per-instrument failures only?
  if "$PY" - "$J" <<'EOF'
import json, sys
d = json.load(open(sys.argv[1]))
ran_through = d.get("stopped") is None and not d.get("aborted") and not d.get("not_attempted")
print(f"intraday: complete={d.get('complete')} failed={d.get('failed')} "
      f"aborted={d.get('aborted')} not_attempted={d.get('not_attempted')} "
      f"stopped={d.get('stopped')}")
sys.exit(0 if ran_through else 1)
EOF
  then verdict="completed_with_instrument_failures"; fi
fi
say "CLOSE_COMPLETED rc=${rc} verdict=${verdict}"

if [[ "$verdict" == "not_completed" ]]; then
  say "BACKFILL_SKIPPED reason=close_not_completed (rc=${rc}); the next scheduled run resumes"
  exit "$rc"
fi

if [[ -f "$J" ]]; then                  # a trading day: the same-day rerun check
  TOKEN="$(grep '^PRAJNA_WRITE_TOKEN=' .env | cut -d= -f2-)"
  args=(); for k in "${RERUN_KEYS[@]}"; do args+=(--key "$k"); done
  R="var/logs/daily/close_${TODAY}_rerun_check.json"
  PRAJNA_UPSTOX_RATE_FRACTION="$CLOSE_FRACTION" "${CLI[@]}" ingest candles --timeframe 1m \
    --timeframe 15m --timeframe 1h --intraday "${args[@]}" --commit --token "$TOKEN" > "$R"
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

say "handing over to the backfill (same lock hold) until ${UNTIL} IST"
PRAJNA_UPSTOX_RATE_FRACTION="$BACKFILL_FRACTION" "$RB/backfill.sh" --login --until "$UNTIL"
brc=$?
exit "$brc"
