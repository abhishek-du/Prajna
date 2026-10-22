#!/usr/bin/env bash
# Forward record of the dashboard's trade plans (user 2026-10-22): once NSE's official
# close is in (the dashboard reads the bhavcopy), every BUY and SELL / AVOID plan of the
# day goes to var/dashboard/signals/<day>.jsonl. Cron 16:45 Mon-Fri; waits for the official
# close until 17:30, then records with the last quotes. Paper research; no order is touched.
set -uo pipefail
cd "$(dirname "$0")/../.."
mkdir -p var/logs/daily
TODAY="$(TZ=Asia/Kolkata date +%F)"
LOG="var/logs/daily/signals_snapshot_${TODAY}.log"
NOTIFY="${PRAJNA_TELEGRAM_CMD:-ops/runbooks/telegram_notify.sh}"
say() { echo "[$(TZ=Asia/Kolkata date '+%F %T IST')] $*" | tee -a "$LOG"; }
ops/runbooks/dashboard.sh start >/dev/null 2>&1
for _ in $(seq 1 60); do curl -s -m 10 http://127.0.0.1:8600/api/health >/dev/null && break; sleep 5; done
until [[ "$(curl -s -m 10 http://127.0.0.1:8600/api/health | .venv/bin/python -c "import json,sys; print(json.load(sys.stdin)['live'].get('official_close_day'))" 2>/dev/null)" == "$TODAY" ]]; do
  if [[ ! "$(TZ=Asia/Kolkata date +%H%M)" < "${PRAJNA_SNAPSHOT_WAIT_UNTIL:-1730}" ]]; then
    say "SIGNALS_SNAPSHOT no official close yet; recording with the last quotes"; break
  fi
  sleep "${PRAJNA_SNAPSHOT_POLL_S:-300}"
done
OUT=""
for _ in 1 2 3; do
  OUT="$(curl -s -m 300 -X POST http://127.0.0.1:8600/api/signals/snapshot)"
  [[ "$OUT" == *'"written"'* || "$OUT" == *'"skipped"'* ]] && break
  sleep 30
done
say "SIGNALS_SNAPSHOT ${OUT:0:300}"
case "$OUT" in *'"written"'*|*'"skipped"'*) ;; *) "$NOTIFY" "Prajna signals snapshot ISSUE: ${OUT:0:200}" >/dev/null 2>&1 || true ;; esac
