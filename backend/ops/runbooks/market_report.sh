#!/usr/bin/env bash
# Daily "Market News & Impact" report (user 2026-10-22): asks the running dashboard
# (http://127.0.0.1:8600) to write it from its facts (Bedrock) and send it to Telegram.
# Cron: 08:45 (pre-market) and 16:20 (after the close) Mon-Fri. Research summary only;
# no order is ever touched. Log: var/logs/daily/market_report_<day>.log.
set -uo pipefail
cd "$(dirname "$0")/../.."
mkdir -p var/logs/daily
LOG="var/logs/daily/market_report_$(TZ=Asia/Kolkata date +%F).log"
NOTIFY="${PRAJNA_TELEGRAM_CMD:-ops/runbooks/telegram_notify.sh}"
say() { echo "[$(TZ=Asia/Kolkata date '+%F %T IST')] $*" | tee -a "$LOG"; }
ops/runbooks/dashboard.sh start >/dev/null 2>&1
for _ in $(seq 1 60); do curl -s -m 5 http://127.0.0.1:8600/api/health >/dev/null && break; sleep 5; done
OUT="$(curl -s -m 300 -X POST "http://127.0.0.1:8600/api/report/generate?telegram=true")"
line="$(printf '%s' "$OUT" | .venv/bin/python -c "import json,sys; d=json.load(sys.stdin); print(d.get('status'), d.get('error') or '', 'telegram', d.get('telegram_sent'))" 2>/dev/null || echo "no answer from the dashboard")"
say "MARKET_REPORT ${line}"
case "$line" in OK*) ;; *) "$NOTIFY" "Prajna market report ISSUE: ${line:0:200}" >/dev/null 2>&1 || true ;; esac
