#!/usr/bin/env bash
# Stage 1 gate checkpoint (decision GATE-INCR, user 2026-10-21; app/acceptance/ohlcv_scan.py).
# The Stage 3 lock evaluates the Stage 1 gate before every snapshot; with a checkpoint it
# scans only the ohlcv_bar rows of runs finished after it (the night's backfill included),
# so the checkpoint is taken after the backfill stops (06:25) and before the 09:00 snapshot.
# Proposed cron (the user installs it): 06:35 every day. Saturday: --full (every bar
# rescanned; it must equal the previous checkpoint + the increment, else an alert).
#
#   ops/runbooks/stage1_checkpoint.sh [--full]
# Log: var/logs/daily/stage1_checkpoint_<day>.log; one STAGE1_CHECKPOINT line per run.
# Test hooks: PRAJNA_CLI, PRAJNA_TELEGRAM_CMD, PRAJNA_TEST_DOW.
set -uo pipefail
cd "$(dirname "$0")/../.."
read -r -a CLI <<< "${PRAJNA_CLI:-.venv/bin/python -m app.cli.main --plain}"
NOTIFY="${PRAJNA_TELEGRAM_CMD:-ops/runbooks/telegram_notify.sh}"
mkdir -p var/logs/daily
TODAY="$(TZ=Asia/Kolkata date +%F)"
LOG="var/logs/daily/stage1_checkpoint_${TODAY}.log"
say() { echo "[$(TZ=Asia/Kolkata date '+%F %T IST')] $*" | tee -a "$LOG"; }
export PRAJNA_SUPPLIED_TOKEN="$(grep '^PRAJNA_WRITE_TOKEN=' .env 2>/dev/null | cut -d= -f2-)"
MODE=()
if [[ "${1:-}" == "--full" || "${PRAJNA_TEST_DOW:-$(TZ=Asia/Kolkata date +%u)}" == "6" ]]; then
  MODE=(--full)
fi
OUT="var/logs/daily/stage1_checkpoint_${TODAY}.json"
t0=$(date +%s)
"${CLI[@]}" acceptance stage1-checkpoint "${MODE[@]}" --commit > "$OUT" 2>> "$LOG"
rc=$?
line="$(.venv/bin/python - "$OUT" <<'PY' 2>/dev/null || echo unreadable
import json, sys
d = json.load(open(sys.argv[1]))
print(f"cut={d.get('cut')} consistent={d.get('consistent')} "
      f"rows={(d.get('counts') or {}).get('rows')}")
PY
)"
say "STAGE1_CHECKPOINT rc=${rc} mode=${MODE[*]:-incremental} seconds=$(( $(date +%s) - t0 )) ${line}"
if [[ $rc -ne 0 ]]; then
  say "STAGE1_CHECKPOINT_ALERT rc=${rc}"
  "$NOTIFY" "Prajna Stage 1 checkpoint ISSUE rc=${rc}: ${line}" >/dev/null 2>&1 || true
fi
exit "$rc"
