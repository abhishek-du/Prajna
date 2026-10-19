#!/usr/bin/env bash
# Event-driven fundamentals (docs/STAGE1_FUNDAMENTALS_RND.md F1 + F2 + F5b, approved by the
# user 2026-10-19). Proposed cron (the user installs it): 13:15 every day. Not at night:
# the backfill holds the vendor's rate budget 16:00-06:25 (fraction 0.9); in the day the
# monthly fundamentals precedent (fraction 0.3 beside the intraday jobs) applies. Results
# are mostly published in the evening, so 13:15 next day meets FUND's "by the end of the
# next trading day".
#
#   ops/runbooks/fundamentals_events.sh
#
# 1 `fundamentals events --commit`   results events from the stored news (no vendor call):
#                                    INTIMATION (results calendar), OUTCOME, ESTIMATE_NEWS
# 2 `fundamentals refresh --commit`  for every instrument with a new OUTCOME, the Upstox
#                                    fundamentals suite again (12 GETs per ISIN, rate
#                                    fraction 0.3, beside the intraday jobs)
# No login here: it uses the day's cached token; a missing / invalid token is an alert.
# Log: var/logs/daily/fundamentals_events_<day>.log; FUNDAMENTALS_EVENTS line per run.
# Test hooks: PRAJNA_CLI, PRAJNA_TELEGRAM_CMD.
set -uo pipefail
cd "$(dirname "$0")/../.."
read -r -a CLI <<< "${PRAJNA_CLI:-.venv/bin/python -m app.cli.main --plain}"
NOTIFY="${PRAJNA_TELEGRAM_CMD:-ops/runbooks/telegram_notify.sh}"
mkdir -p var/logs/daily
TODAY="$(TZ=Asia/Kolkata date +%F)"
LOG="var/logs/daily/fundamentals_events_${TODAY}.log"
say() { echo "[$(TZ=Asia/Kolkata date '+%F %T IST')] $*" | tee -a "$LOG"; }
alert() { say "FUNDAMENTALS_EVENTS_ALERT $*"; "$NOTIFY" "Prajna fundamentals ISSUE: $*" >/dev/null 2>&1 || true; }
# the write token travels in the environment, never in argv (visible to ps)
export PRAJNA_SUPPLIED_TOKEN="$(grep '^PRAJNA_WRITE_TOKEN=' .env 2>/dev/null | cut -d= -f2-)"
export PRAJNA_UPSTOX_RATE_FRACTION="${PRAJNA_UPSTOX_RATE_FRACTION:-0.3}"

EV="var/logs/daily/fundamentals_events_${TODAY}_events.json"
if ! "${CLI[@]}" fundamentals events --commit > "$EV" 2>> "$LOG"; then
  alert "events step failed (see $LOG)"; exit 1
fi
RF="var/logs/daily/fundamentals_events_${TODAY}_refresh.json"
"${CLI[@]}" fundamentals refresh --commit > "$RF" 2>> "$LOG"
rc=$?
line="$(.venv/bin/python - "$EV" "$RF" <<'EOF' 2>/dev/null || echo "unreadable output"
import json, sys
e, r = (json.load(open(p)) for p in sys.argv[1:3])
print(f"inserted_events={e.get('inserted')} by_kind={e.get('by_kind')} due={r.get('due')} "
      f"refreshed={r.get('refreshed')} snapshots={r.get('inserted')} "
      f"problems={len(r.get('problems') or [])} stopped={r.get('stopped')}")
EOF
)"
say "FUNDAMENTALS_EVENTS rc=${rc} ${line}"
if [[ $rc -ne 0 ]]; then alert "refresh rc=${rc}: ${line}"; fi
exit "$rc"
