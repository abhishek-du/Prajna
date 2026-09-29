#!/usr/bin/env bash
# Multi-source news collection into the database for TODAY (IST), until a time.
#
#   ops/runbooks/news_collect.sh --mode SHADOW|PRODUCTION --sources ALL|KEY[,KEY] \
#       --until HH:MM [--token-from-dotenv]
#
# - One collector at a time: flock -n on var/run/news_collect.lock. A second start
#   while one runs exits 1 with marker NEWS_COLLECT_SKIP and polls nothing.
# - Calls ONLY `prajna news collect`: every poll re-checks the source's own flag,
#   the kill switch, terms, the source's acceptance PASS, Stage 2 and the token
#   (and PRODUCTION: PRAJNA_NEWS_MULTI_SOURCE_ENABLED). A refusal stops that
#   source, is audited in news_audit and writes nothing; if every source is
#   refused the marker is NEWS_COLLECT_REFUSED. There is no bypass.
# - The token travels in the environment only (PRAJNA_SUPPLIED_TOKEN), never in
#   argv, and is never printed; --token-from-dotenv reads it from .env at run time.
# - Markers: NEWS_COLLECT_START / DONE / REFUSED / FAILED / SKIP.
set -uo pipefail
USAGE="usage: $0 --mode SHADOW|PRODUCTION --sources ALL|KEY[,KEY] --until HH:MM [--token-from-dotenv]"
MODE="" SOURCES="" UNTIL="" DOTENV=0
while (( $# )); do
  case "$1" in
    --mode) MODE="${2:-}"; shift 2 ;;
    --sources) SOURCES="${2:-}"; shift 2 ;;
    --until) UNTIL="${2:-}"; shift 2 ;;
    --token-from-dotenv) DOTENV=1; shift ;;
    *) echo "$USAGE" >&2; exit 2 ;;
  esac
done
[[ "$MODE" == SHADOW || "$MODE" == PRODUCTION ]] || { echo "$USAGE" >&2; exit 2; }
[[ -n "$SOURCES" && "$UNTIL" =~ ^[0-9]{2}:[0-9]{2}$ ]] || { echo "$USAGE" >&2; exit 2; }
cd "$(dirname "$0")/../.."
mkdir -p var/logs/daily var/run
TODAY="$(TZ=Asia/Kolkata date +%F)"
exec > >(tee -a "var/logs/daily/news_collect_${TODAY}.log") 2>&1
say() { echo "[$(TZ=Asia/Kolkata date '+%F %T IST')] $*"; }
if [[ $DOTENV == 1 ]]; then
  PRAJNA_SUPPLIED_TOKEN="$(grep '^PRAJNA_WRITE_TOKEN=' .env | cut -d= -f2-)"
  export PRAJNA_SUPPLIED_TOKEN
fi

exec 9> var/run/news_collect.lock
if ! flock -n 9; then
  say "NEWS_COLLECT_SKIP ${MODE} ${TODAY}: another collector holds var/run/news_collect.lock"
  exit 1
fi

say "NEWS_COLLECT_START ${MODE} ${SOURCES} until ${UNTIL}"
out="var/logs/daily/news_collect_${TODAY}_${MODE}.json"
.venv/bin/python -m app.cli.main --plain news collect --source "$SOURCES" --mode "$MODE" \
    --until "$UNTIL" > "$out"
rc=$?
cat "$out"
case $rc in
  0) say "NEWS_COLLECT_DONE ${MODE} ${TODAY}" ;;
  3) say "NEWS_COLLECT_REFUSED ${MODE} ${TODAY}: every source refused by its locks; nothing written" ;;
  *) say "NEWS_COLLECT_FAILED ${MODE} ${TODAY} (exit ${rc})" ;;
esac
exit $rc
