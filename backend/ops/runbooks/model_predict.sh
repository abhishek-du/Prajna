#!/usr/bin/env bash
# E5 daily prediction (docs/STAGE4_E5_PREREGISTRATION.md; approved by the user 2026-10-21).
# PAPER ONLY: it writes model_prediction rows; nothing places, modifies or cancels an order.
# Proposed cron (the user installs it): 09:06 Monday-Friday.
#
#   ops/runbooks/model_predict.sh
#
# 1 not a trading day -> MODEL_PREDICT_SKIP
# 2 waits (until 09:13 IST) for today's Stage 3 PRE_SESSION run (STAGE3_DONE PRE_SESSION
#   <day> in var/logs/daily/stage3_<day>.log); not done by then -> MODEL_PREDICT_ALERT missed
# 3 `models predict --commit` (refused by the code itself at/after the 09:15 open)
# Log: var/logs/daily/model_predict_<day>.log; one MODEL_PREDICT line per run.
# Test hooks: PRAJNA_CLI, PRAJNA_TELEGRAM_CMD, PRAJNA_TEST_NOW_HHMM, PRAJNA_TEST_TRADING_DAY,
# PRAJNA_PREDICT_WAIT_UNTIL (HHMM), PRAJNA_PREDICT_POLL_S.
set -uo pipefail
cd "$(dirname "$0")/../.."
read -r -a CLI <<< "${PRAJNA_CLI:-.venv/bin/python -m app.cli.main --plain}"
NOTIFY="${PRAJNA_TELEGRAM_CMD:-ops/runbooks/telegram_notify.sh}"
mkdir -p var/logs/daily
TODAY="$(TZ=Asia/Kolkata date +%F)"
LOG="var/logs/daily/model_predict_${TODAY}.log"
say() { echo "[$(TZ=Asia/Kolkata date '+%F %T IST')] $*" | tee -a "$LOG"; }
alert() { say "MODEL_PREDICT_ALERT $*"; "$NOTIFY" "Prajna model ISSUE: $*" >/dev/null 2>&1 || true; }
hhmm() { echo "${PRAJNA_TEST_NOW_HHMM:-$(TZ=Asia/Kolkata date +%H%M)}"; }
# the write token travels in the environment, never in argv (visible to ps)
export PRAJNA_SUPPLIED_TOKEN="$(grep '^PRAJNA_WRITE_TOKEN=' .env 2>/dev/null | cut -d= -f2-)"

td="${PRAJNA_TEST_TRADING_DAY:-$("${CLI[@]}" db sql "select is_trading_day from trading_session where session_date = '${TODAY}'" 2>/dev/null | sed -n 3p | tr -d ' ' | tr 'A-Z' 'a-z')}"
if [[ "$td" != "true" ]]; then say "MODEL_PREDICT_SKIP not a trading day (${td:-unknown})"; exit 0; fi

UNTIL="${PRAJNA_PREDICT_WAIT_UNTIL:-0913}"
S3="var/logs/daily/stage3_${TODAY}.log"
until grep -q "STAGE3_DONE PRE_SESSION ${TODAY}" "$S3" 2>/dev/null; do
  if [[ ! "$(hhmm)" < "$UNTIL" ]]; then
    alert "missed ${TODAY}: no Stage 3 PRE_SESSION run by ${UNTIL} IST; no prediction"
    exit 3
  fi
  sleep "${PRAJNA_PREDICT_POLL_S:-10}"
done

OUT="var/logs/daily/model_predict_${TODAY}.json"
"${CLI[@]}" models predict --commit > "$OUT" 2>> "$LOG"
rc=$?
line="$(.venv/bin/python - "$OUT" <<'EOF' 2>/dev/null || echo "unreadable output"
import json, sys
d = json.load(open(sys.argv[1]))
if "refused" in d:
    print(f"refused={d['refused'][:160]}")
else:
    print(f"inserted={d.get('inserted')} universe={d.get('universe')} "
          f"history={d.get('history_sessions')} picks={len(d.get('picks') or [])} "
          f"excluded_results={d.get('results_today_excluded')}")
EOF
)"
say "MODEL_PREDICT rc=${rc} ${line}"
if [[ $rc -ne 0 ]]; then alert "predict rc=${rc}: ${line}"; fi
exit "$rc"
