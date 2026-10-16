#!/usr/bin/env bash
# Stage 8: the PAPER report of each strategy to Telegram (and var/logs/paper/).
#
#   ops/runbooks/paper_report.sh [--days N] [--strategies a,b] [--no-telegram]
#
# Read-only on the database (prajna paper report). NOT scheduled: a cron line needs the
# user's approval. The text always carries the PAPER-ONLY disclaimer.
set -uo pipefail
cd "$(dirname "$0")/../.."
P="${PRAJNA_PY:-.venv/bin/python}"
NOTIFY="${PRAJNA_TELEGRAM_CMD:-ops/runbooks/telegram_notify.sh}"
DAYS=30; STRATS="baseline_gap_fade,baseline_c0"; SEND=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --days) DAYS="$2"; shift 2 ;;
    --strategies) STRATS="$2"; shift 2 ;;
    --no-telegram) SEND=0; shift ;;
    *) echo "usage: $0 [--days N] [--strategies a,b] [--no-telegram]" >&2; exit 2 ;;
  esac
done
mkdir -p var/logs/paper
TO="$(TZ=Asia/Kolkata date +%F)"; FROM="$(TZ=Asia/Kolkata date -d "-${DAYS} days" +%F)"
OUT="var/logs/paper/report_${TO}.txt"; : > "$OUT"
rc=0
IFS=',' read -ra LIST <<< "$STRATS"
for st in "${LIST[@]}"; do
  if ! "$P" -m app.cli.main --plain paper report --strategy "$st" --from "$FROM" --to "$TO" \
       --text >> "$OUT" 2>> var/logs/paper/report_errors.log; then
    echo "Prajna PAPER report ${st}: FAILED (see var/logs/paper/report_errors.log)" >> "$OUT"
    rc=1
  fi
  echo >> "$OUT"
done
cat "$OUT"
if (( SEND )); then "$NOTIFY" "$(cat "$OUT")" >/dev/null 2>&1 || rc=1; fi
exit "$rc"
