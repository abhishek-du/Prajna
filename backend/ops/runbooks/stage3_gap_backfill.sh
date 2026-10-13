#!/usr/bin/env bash
# Stage 3 feature backfill of the 7 production gap sessions (BACKFILL-DEFER; NOT RUN).
#
#   ops/runbooks/stage3_gap_backfill.sh                 # --plan (default): read-only
#   ops/runbooks/stage3_gap_backfill.sh --execute --confirm GAP-2026-09-30..2026-10-12
#
# Sessions: 2026-09-30, 10-01, 10-05, 10-06, 10-07, 10-09, 10-12 (both snapshots).
# 2026-10-08 is skipped TWICE: it is outside both bounded ranges, and its rows belong
# to registry dd696ca6, so the engine refuses it anyway (RegistryConflict, ac3cbb2).
#
# --execute, in order (any failure stops; nothing is retried):
#   1 refuse 08:25-10:15 IST on a trading day (pre-open, Stage 3 cron, shadow)
#   2 the Stage 3 lock (var/run/stage3.lock), as stage3_snapshot.sh
#   3 a verified backup: ops/runbooks/db_backup.sh --label stage3_gap_backfill
#   4 fingerprint BEFORE (every stored session: rows, registries, md5)
#   5 two bounded commands; PRAJNA_STAGE3_BACKFILL_ENABLED=true is set in THOSE TWO
#     processes' environment only (.env is not edited); the token travels in env
#   6 fingerprint AFTER; compare: every stored session byte-identical, the only new
#     sessions are the 7 above - otherwise exit 1 (restore from the backup)
# The engine itself keeps every RUN protection: lock conditions, point-in-time
# check, determinism-mismatch refusal (never overwrites), idempotent inserts.
set -euo pipefail
cd "$(dirname "$0")/../.."
P="${PRAJNA_PY:-.venv/bin/python}"
CLI=("$P" -m app.cli.main --plain)
CONFIRM="GAP-2026-09-30..2026-10-12"
RANGES=("2026-09-30 2026-10-07" "2026-10-09 2026-10-12")
SESSIONS="2026-09-30,2026-10-01,2026-10-05,2026-10-06,2026-10-07,2026-10-09,2026-10-12"
MODE=plan; GIVEN=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --plan) MODE=plan; shift ;;
    --execute) MODE=execute; shift ;;
    --confirm) GIVEN="$2"; shift 2 ;;
    *) echo "usage: $0 [--plan] | --execute --confirm ${CONFIRM}" >&2; exit 2 ;;
  esac
done
say() { echo "[$(TZ=Asia/Kolkata date '+%F %T IST')] $*"; }

if [[ $MODE == plan ]]; then
  say "STAGE3_GAP_PLAN (read-only)"
  "$P" - <<'PY'
import asyncio, datetime as dt
from sqlalchemy import text
from app.db.engine import get_sessionmaker
from app.features import engine as E, snapshots as SN
RANGES = [(dt.date(2026, 9, 30), dt.date(2026, 10, 7)), (dt.date(2026, 10, 9), dt.date(2026, 10, 12))]
async def go():
    async with get_sessionmaker()() as s:
        await s.execute(text("set transaction isolation level repeatable read, read only"))
        plan = [d for a, b in RANGES for d in await SN.sessions_between(s, a, b)]
        print("sessions:", ", ".join(map(str, plan)), "| 2026-10-08 in plan:",
              dt.date(2026, 10, 8) in plan)
        for d in plan:
            for k in ("PRE_SESSION", "PRE_OPEN"):
                snap = await SN.resolve(s, d, k)
                stored = (await s.execute(text("select count(*) from feature_value where "
                    "session_date = :d and snapshot = :k"), {"d": d, "k": k})).scalar()
                other = await E.other_registry_rows(s, snap)
                print(f"  {d} {k:11} stored={stored} other_registry={sum(other.values())} -> "
                      f"{'SKIP' if other else ('NO-OP' if stored else 'BACKFILL')}")
        await s.rollback()
asyncio.run(go())
PY
  for r in "${RANGES[@]}"; do
    set -- $r
    say "  PRAJNA_STAGE3_BACKFILL_ENABLED=true ${CLI[*]} stage3 backfill --from $1 --to $2 --commit"
  done
  say "plan only: nothing written"
  exit 0
fi

[[ "$GIVEN" == "$CONFIRM" ]] || { say "REFUSED: --execute needs --confirm ${CONFIRM}"; exit 2; }
hhmm="${PRAJNA_TEST_NOW_HHMM:-$(TZ=Asia/Kolkata date +%H%M)}"
if [[ ! "$hhmm" < "0825" && "$hhmm" < "1015" ]]; then
  say "REFUSED: 08:25-10:15 IST belongs to the pre-open and the Stage 3 cron"; exit 3
fi
mkdir -p var/run var/logs/stage3_gap
exec 9> var/run/stage3.lock
flock -w 60 9 || { say "REFUSED: another Stage 3 run holds var/run/stage3.lock"; exit 3; }
STAMP="$(TZ=Asia/Kolkata date +%Y%m%dT%H%M)"
D="var/logs/stage3_gap/${STAMP}"; mkdir -p "$D"
say "1/4 backup"
ops/runbooks/db_backup.sh --label stage3_gap_backfill
say "2/4 fingerprint before"
"$P" ops/measure/feature_fingerprint.py --out "$D/before.json" > /dev/null
export PRAJNA_SUPPLIED_TOKEN="$(grep '^PRAJNA_WRITE_TOKEN=' .env | cut -d= -f2-)"
say "3/4 backfill (two bounded ranges)"
for r in "${RANGES[@]}"; do
  set -- $r
  PRAJNA_STAGE3_BACKFILL_ENABLED=true "${CLI[@]}" stage3 backfill --from "$1" --to "$2" --commit \
    > "$D/backfill_$1_$2.json"
  say "   $1..$2 done"
done
say "4/4 fingerprint after + compare"
"$P" ops/measure/feature_fingerprint.py --out "$D/after.json" > /dev/null
"$P" ops/measure/feature_fingerprint.py --compare "$D/before.json" "$D/after.json" \
  --expect-new "$SESSIONS" | tee "$D/compare.json"
say "STAGE3_GAP_DONE evidence in ${D}"
