#!/usr/bin/env bash
# Nightly reconciliation of the multi-source news collector (read-only).
#
#   ops/runbooks/news_reconcile.sh [--day YYYY-MM-DD] [--mode PRODUCTION|SHADOW]
#
# A separate responsibility from collection (news_collect.sh): it only READS the
# database, writes var/news/reconcile/<day>_<mode>.json (+ .md), updates
# var/status/news_health.json (shown by `prajna ops status`), and exits 4 with
# marker NEWS_RECONCILE_VIOLATED if any invariant fails (duplicate source ids,
# knowable before discovery, an article without a decision, a decision or an
# enrichment knowable too early, anything knowable in the future).
# Markers: NEWS_RECONCILE_START / OK / VIOLATED / FAILED.
set -uo pipefail
DAY="" MODE="PRODUCTION"
while (( $# )); do
  case "$1" in
    --day) DAY="${2:-}"; shift 2 ;;
    --mode) MODE="${2:-}"; shift 2 ;;
    *) echo "usage: $0 [--day YYYY-MM-DD] [--mode PRODUCTION|SHADOW]" >&2; exit 2 ;;
  esac
done
[[ "$MODE" == PRODUCTION || "$MODE" == SHADOW ]] || { echo "bad --mode" >&2; exit 2; }
cd "$(dirname "$0")/../.."
DAY="${DAY:-$(TZ=Asia/Kolkata date +%F)}"
mkdir -p var/logs/daily var/news/reconcile
exec > >(tee -a "var/logs/daily/news_reconcile_${DAY}.log") 2>&1
say() { echo "[$(TZ=Asia/Kolkata date '+%F %T IST')] $*"; }
out="var/news/reconcile/${DAY}_${MODE}"
say "NEWS_RECONCILE_START ${MODE} ${DAY}"
.venv/bin/python -m app.cli.main --plain news reconcile --day "$DAY" --mode "$MODE" \
    --md "${out}.md" --json "${out}.json"
rc=$?
case $rc in
  0) say "NEWS_RECONCILE_OK ${MODE} ${DAY} (${out}.json)" ;;
  4) say "NEWS_RECONCILE_VIOLATED ${MODE} ${DAY}: an invariant failed (${out}.json)" ;;
  *) say "NEWS_RECONCILE_FAILED ${MODE} ${DAY} (exit ${rc})" ;;
esac
exit $rc
