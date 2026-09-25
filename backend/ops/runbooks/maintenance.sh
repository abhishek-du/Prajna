#!/usr/bin/env bash
# Daily operations maintenance (hardening phase 4). No vendor calls.
#
#   ops/runbooks/maintenance.sh [reap|derive|status|all]     # default all
#
# reap    `prajna ops reap-runs --commit`: RUNNING ingest runs whose process
#         is provably gone (pid dead, machine rebooted, or no identity and
#         > 48 h) become ABORTED with the reason (MAINT_REAP marker)
# derive  price basis for any payload lacking one, corporate-action factors
#         (+ the vendor's observed treatment), global instrument contracts
#         (MAINT_DERIVE marker); all idempotent, no vendor calls
# status  `prajna ops status --write`: var/status/ops_status_<stamp>.json -
#         last run per job family, RUNNING runs, candles lock, token age,
#         disk, recent runbook markers (MAINT_STATUS marker, with a summary)
set -uo pipefail
WHAT="${1:-all}"
cd "$(dirname "$0")/../.."
P=.venv/bin/python
CLI=("$P" -m app.cli.main --plain)
mkdir -p var/logs/daily
TODAY="$(TZ=Asia/Kolkata date +%F)"
exec > >(tee -a "var/logs/daily/maintenance_${TODAY}.log") 2>&1
# the write token travels in the environment, never in argv (visible to ps)
export PRAJNA_SUPPLIED_TOKEN="$(grep '^PRAJNA_WRITE_TOKEN=' .env | cut -d= -f2-)"
say() { echo "[$(TZ=Asia/Kolkata date '+%F %T IST')] $*"; }
rc=0
DERIVE=(price-basis ca-factors)

summ() {  # summ <kind> <json>: one-line summary of a command's JSON output
  "$P" - "$1" "$2" <<'EOF' 2>/dev/null || echo "FAILED (unreadable output)"
import json, sys
kind, d = sys.argv[1], json.loads(sys.argv[2])
if kind == "reap":
    print(f"running={d['running']} reaped={len(d['orphans'])} "
          f"left_alone={len(d['left_alone'])} run={d['run_id']}")
else:
    bad = {k: v["last_status"] for k, v in d["families"].items()
           if v["last_status"] not in (None, "COMPLETE")}
    print(f"lock={d['candles_lock']} running={d['running']['count']} "
          f"disk_free_gb={d['disk_free_gb']} not_complete={bad}")
EOF
}

if [[ "$WHAT" == reap || "$WHAT" == all ]]; then
  out="$("${CLI[@]}" ops reap-runs --commit 2>/dev/null)" || rc=1
  say "MAINT_REAP $(summ reap "$out")"
fi
if [[ "$WHAT" == derive || "$WHAT" == all ]]; then
  for d in "${DERIVE[@]}"; do
    if "${CLI[@]}" derive "$d" --commit > "var/logs/daily/maintenance_${TODAY}_${d}.json" 2>/dev/null
    then say "MAINT_DERIVE ${d} OK"; else say "MAINT_DERIVE ${d} FAILED"; rc=1; fi
  done
fi
if [[ "$WHAT" == status || "$WHAT" == all ]]; then
  out="$("${CLI[@]}" ops status --write 2>/dev/null)" || rc=1
  say "MAINT_STATUS $(summ status "$out")"
fi
exit $rc
