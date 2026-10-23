#!/usr/bin/env bash
# E6 post-results drift PAPER MONITOR (docs/STAGE4_E6_PREREGISTRATION.md; decisions 2026-10-23).
# Cron 08:50 Mon-Fri, after the 08:32 morning job stored yesterday's daily bars and before the
# 09:15 open (the entry): records today's picks and controls, then a Telegram heartbeat of
# counts only. Files only (var/research/e6); PAPER RESEARCH; no order is touched.
set -uo pipefail
cd "$(dirname "$0")/../.."
P="${PRAJNA_PY:-.venv/bin/python}"
NOTIFY="${PRAJNA_TELEGRAM_CMD:-ops/runbooks/telegram_notify.sh}"
DAY="$(TZ=Asia/Kolkata date +%F)"
LOG="var/logs/daily/e6_${DAY}.log"
mkdir -p var/logs/daily var/run
say() { echo "[$(TZ=Asia/Kolkata date '+%F %T IST')] $*" | tee -a "$LOG"; }
exec 9> var/run/e6.lock
flock -n 9 || { say "E6_SKIP another run holds the lock"; exit 0; }
OUT="$("$P" -m app.cli.main --plain e6 record --commit 2>&1)"; rc=$?
REC="$(echo "$OUT" | tr -d '\n' | cut -c1-400)"
say "E6_RECORD rc=$rc $REC"
ST="$("$P" -m app.cli.main --plain e6 status 2>&1 | tr -d '\n' | cut -c1-600)"
say "E6_STATUS $ST"
if [[ $rc -ne 0 || "$OUT" == *TOO_LATE* ]]; then
  "$NOTIFY" "Prajna E6 monitor ISSUE: ${REC:0:300}" >/dev/null 2>&1 || true
else
  "$NOTIFY" "Prajna E6 monitor (paper): ${REC:0:300}" >/dev/null 2>&1 || true
fi
exit $rc
