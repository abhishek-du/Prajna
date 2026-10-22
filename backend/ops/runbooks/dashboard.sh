#!/usr/bin/env bash
# Prajna research dashboard (user 2026-10-22): read-only web view on http://127.0.0.1:8600
# (bound to localhost only). Starts it unless it is already running; safe to call from cron
# (@reboot and every 10 min as a keep-alive). PAPER RESEARCH ONLY: no order is touched.
#
#   ops/runbooks/dashboard.sh [start|stop|status]
#
# The Bedrock key for the on-demand AI notes travels from .env into the process
# environment only (never argv, never printed). Log: var/logs/dashboard.log.
set -uo pipefail
cd "$(dirname "$0")/../.."
mkdir -p var/logs var/run
PORT="${PRAJNA_DASHBOARD_PORT:-8600}"
PIDF=var/run/dashboard.pid
running() { [[ -f "$PIDF" ]] && kill -0 "$(cat "$PIDF")" 2>/dev/null; }
case "${1:-start}" in
  status) if running; then echo "running pid $(cat "$PIDF") http://127.0.0.1:${PORT}"; else echo "stopped"; fi ;;
  stop) if running; then kill "$(cat "$PIDF")" && rm -f "$PIDF" && echo stopped; else echo "not running"; fi ;;
  start)
    if running; then exit 0; fi
    AWS_BEARER_TOKEN_BEDROCK="$(grep '^AWS_BEARER_TOKEN_BEDROCK=' .env 2>/dev/null | cut -d= -f2-)"
    [[ -n "$AWS_BEARER_TOKEN_BEDROCK" ]] && export AWS_BEARER_TOKEN_BEDROCK
    nohup .venv/bin/python -m app.dashboard --host 127.0.0.1 --port "$PORT" >> var/logs/dashboard.log 2>&1 &
    echo $! > "$PIDF"
    echo "[$(TZ=Asia/Kolkata date '+%F %T IST')] DASHBOARD_STARTED pid $! http://127.0.0.1:${PORT}" | tee -a var/logs/dashboard.log
    ;;
  *) echo "usage: $0 [start|stop|status]" >&2; exit 2 ;;
esac
