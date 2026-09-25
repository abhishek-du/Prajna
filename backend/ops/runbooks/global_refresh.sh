#!/usr/bin/env bash
# Daily global 1D refresh (hardening phase 5). 13 requests; no candles lock
# needed (it runs at fraction 0.1 beside any other candle job; the per-user
# quota sums stay <= 0.9).
#
#   ops/runbooks/global_refresh.sh
#
# Fetches the last 7 labels of every global instrument. Under the finality
# contract (migration 0010) the FIRST observation of a label is stored but not
# exposed; a later unchanged re-observation (REOBSERVED) >= confirm_hours later
# makes it CONFIRMED; a changed one (GLOBAL_REVISION) makes it REVISED and it is
# never exposed. Two runs a day (cron 12:40 and 21:10 IST) give the confirmation.
# Markers: GLOBAL_REFRESH_STARTED / COMPLETED / PARTIAL, GLOBAL_REVISION_DETECTED,
# GLOBAL_VENDOR_ABSENT, GLOBAL_FINALITY.
set -uo pipefail
cd "$(dirname "$0")/../.."
P=.venv/bin/python
CLI=("$P" -m app.cli.main --plain)
mkdir -p var/logs/daily
TODAY="$(TZ=Asia/Kolkata date +%F)"
STAMP="$(TZ=Asia/Kolkata date +%H%M)"
exec > >(tee -a "var/logs/daily/global_refresh_${TODAY}.log") 2>&1
# the write token travels in the environment, never in argv (visible to ps)
export PRAJNA_SUPPLIED_TOKEN="$(grep '^PRAJNA_WRITE_TOKEN=' .env | cut -d= -f2-)"
export PRAJNA_UPSTOX_RATE_FRACTION="${PRAJNA_UPSTOX_RATE_FRACTION:-0.1}"
say() { echo "[$(TZ=Asia/Kolkata date '+%F %T IST')] $*"; }

FROM="$(TZ=Asia/Kolkata date -d "${TODAY} -7 days" +%F)"
say "GLOBAL_REFRESH_STARTED window=${FROM}..${TODAY} fraction=${PRAJNA_UPSTOX_RATE_FRACTION}"
if ! "${CLI[@]}" upstox token-status | grep -q '"valid": true'; then
  say "GLOBAL_REFRESH_PARTIAL reason=TOKEN_FAILURE (token invalid; no login here - the"\
      "morning jobs own the day's single login)"
  exit 3
fi
OUT="var/logs/daily/global_refresh_${TODAY}_${STAMP}.json"
timeout -k 60 --signal=INT 900 "${CLI[@]}" ingest candles --timeframe 1d --global \
  --from "$FROM" --to "$TODAY" --commit > "$OUT"
rc=$?
"$P" - "$OUT" "$rc" <<'EOF' | while read -r line; do say "$line"; done
import json, sys
rc = int(sys.argv[2])
try:
    d = json.load(open(sys.argv[1]))
except Exception as e:
    print(f"GLOBAL_REFRESH_PARTIAL reason=unreadable_report rc={rc} ({type(e).__name__})")
    raise SystemExit(0)
obs = d.get("observations") or {}
stopped = d.get("stopped")
state = "COMPLETED" if rc == 0 and not stopped and not d.get("failed") else "PARTIAL"
print(f"GLOBAL_REFRESH_{state} rc={rc} jobs={d.get('jobs')} complete={d.get('complete')} "
      f"inserted={d.get('inserted')} failed={len(d.get('failed') or [])} stopped={stopped}")
print(f"GLOBAL_REVISION_DETECTED count={obs.get('GLOBAL_REVISION', 0)} "
      f"reobserved={obs.get('REOBSERVED', 0)}")
EOF
"${CLI[@]}" db sql "select 'GLOBAL_VENDOR_ABSENT', count(*) from canon_global_vendor_absent where absent_date >= current_date - 7" 2>/dev/null | sed -n 3p | while read -r m n; do say "GLOBAL_VENDOR_ABSENT last7d=${n}"; done
fin="$("${CLI[@]}" db sql "select finality, count(*) from global_bar_finality where session_date >= current_date - 10 group by 1 order by 1" 2>/dev/null | sed -n '3,9p' | awk 'NF==2 && $2 != "row(s)" {printf "%s=%s ", $1, $2}')"
say "GLOBAL_FINALITY last10d: ${fin}"
exit $rc
