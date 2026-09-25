#!/usr/bin/env bash
# Intraday news polling (hardening: live inputs). ~118 requests / ~1 min per
# run on the news API (its own per-user quota, not the candles one).
#
#   ops/runbooks/news_poll.sh
#
# Measured 2026-09-25: with news fetched only at the 16:05 close and the 07:00
# morning run, received_at trailed published_at by a median 51 h (p90 166 h).
# Polling every 30 min in market hours brings received_at close to publication;
# knowable_at stays the vendor's published time (verified), received_at =
# fetched_at, processed_at = the run's finished_at. Markers: NEWS_POLL_STARTED /
# NEWS_POLL_COMPLETED / NEWS_POLL_FAILED.
set -uo pipefail
cd "$(dirname "$0")/../.."
P=.venv/bin/python
CLI=("$P" -m app.cli.main --plain)
mkdir -p var/logs/daily
TODAY="$(TZ=Asia/Kolkata date +%F)"
exec > >(tee -a "var/logs/daily/news_poll_${TODAY}.log") 2>&1
# the write token travels in the environment, never in argv (visible to ps)
export PRAJNA_SUPPLIED_TOKEN="$(grep '^PRAJNA_WRITE_TOKEN=' .env | cut -d= -f2-)"
export PRAJNA_UPSTOX_RATE_FRACTION="${PRAJNA_UPSTOX_RATE_FRACTION:-0.2}"
say() { echo "[$(TZ=Asia/Kolkata date '+%F %T IST')] $*"; }
say "NEWS_POLL_STARTED"
if ! "${CLI[@]}" upstox token-status | grep -q '"valid": true'; then
  say "NEWS_POLL_FAILED reason=TOKEN_FAILURE (no login here; the morning jobs own it)"; exit 3
fi
OUT="var/logs/daily/news_poll_${TODAY}_$(TZ=Asia/Kolkata date +%H%M).json"
timeout -k 60 --signal=INT 900 "${CLI[@]}" ingest news --commit > "$OUT" 2>/dev/null
rc=$?
summary="$("$P" - "$OUT" <<'EOF' 2>/dev/null || echo "unreadable report"
import json, sys
d = json.load(open(sys.argv[1]))
print(" ".join(f"{k}={d.get(k)}" for k in ("batches", "articles_seen", "inserted",
                                            "links_inserted", "failed", "stopped")))
EOF
)"
if [[ $rc -eq 0 ]]; then say "NEWS_POLL_COMPLETED ${summary}"; else say "NEWS_POLL_FAILED rc=${rc} ${summary}"; fi
exit $rc
