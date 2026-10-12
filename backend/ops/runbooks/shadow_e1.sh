#!/usr/bin/env bash
# E1 shadow log (approved 2026-10-12). LOGGING ONLY: no order, no broker call, no
# database write. Cron (weekdays):
#   06 09  shadow_e1.sh picks   - picks from today's PRE_SESSION features, before 09:15
#   45 09  shadow_e1.sh open    - opening quotes (pre-open capture replay) + outcomes of
#                                 earlier days whose canonical daily bars exist
set -uo pipefail
cd "$(dirname "$0")/../.."
PHASE="${1:?usage: shadow_e1.sh picks|open}"
LOG="var/logs/daily/shadow_e1_$(TZ=Asia/Kolkata date +%F).log"
mkdir -p var/logs/daily
ts() { TZ=Asia/Kolkata date '+%F %T IST'; }
{
  echo "[$(ts)] SHADOW_E1_START $PHASE"
  case "$PHASE" in
    picks) .venv/bin/python ops/measure/shadow_e1.py picks; rc=$? ;;
    open)  .venv/bin/python ops/measure/shadow_e1.py open; rc=$?
           .venv/bin/python ops/measure/shadow_e1.py outcomes; rc2=$?
           [ "$rc" -eq 0 ] && rc=$rc2 ;;
    *) echo "unknown phase $PHASE"; rc=2 ;;
  esac
  echo "[$(ts)] SHADOW_E1_END $PHASE rc=$rc"
} >> "$LOG" 2>&1
exit "${rc:-1}"
