#!/usr/bin/env bash
# E5.1 training data (docs/STAGE4_E5_AFTER_THE_LOOK.md, prerequisites 1-2; user 2026-10-22).
# PAPER/RESEARCH only: it writes training tables; no order is ever touched.
#
#   ops/runbooks/e51_data.sh daily                     (cron 10:05 Mon-Fri)
#   ops/runbooks/e51_data.sh backfill FROM TO [SHARDS] (one-off; SHARDS parallel builders)
#
# daily, in this order (a sample is final - append-only - so a session is sampled only
# once its labels exist; otherwise it would be NO_LABEL for ever):
#   1 label-v2 for the closed sessions after the last labelled one, up to yesterday
#     (their canonical daily bars arrive with the 07:00 job)
#   2 the AS_IF_LIVE dataset (stage4-ds-v4b-asif, PRE_SESSION) for the sessions after the
#     last built one, up to the last labelled session
#   3 training samples of (v4b-asif, label-v2)
# One run at a time (var/run/e51_data.lock). Log: var/logs/daily/e51_data_<day>.log;
# E51_DATA lines; Telegram on a failure.
set -uo pipefail
cd "$(dirname "$0")/../.."
mkdir -p var/logs/daily var/run
TODAY="$(TZ=Asia/Kolkata date +%F)"
LOG="var/logs/daily/e51_data_${TODAY}.log"
NOTIFY="${PRAJNA_TELEGRAM_CMD:-ops/runbooks/telegram_notify.sh}"
CLI=(.venv/bin/python -m app.cli.main --plain)
say() { echo "[$(TZ=Asia/Kolkata date '+%F %T IST')] $*" | tee -a "$LOG"; }
fail() { say "E51_DATA_FAILED $*"; "$NOTIFY" "Prajna E5.1 data ISSUE: $*" >/dev/null 2>&1 || true; exit 1; }
export PRAJNA_SUPPLIED_TOKEN="$(grep '^PRAJNA_WRITE_TOKEN=' .env 2>/dev/null | cut -d= -f2-)"

exec 9> var/run/e51_data.lock
flock -n 9 || { say "E51_DATA_SKIP another run holds var/run/e51_data.lock"; exit 0; }

plan() {   # prints: last_labelled last_built yesterday_session
  .venv/bin/python - <<'PY'
import asyncio
from sqlalchemy import text
from app.db.engine import get_sessionmaker
from app.training import policy as P
async def go():
    async with get_sessionmaker()() as s:
        q = lambda sql, **k: s.execute(text(sql), k)
        lab = (await q("select max(session_date) from training_label where label_version = 'label-v2'")).scalar()
        built = (await q("select max(session_date) from training_session_done where dataset_version = :v",
                         v=P.DATASETS["asif"].version)).scalar()
        prev = (await q("""select max(session_date) from trading_session where is_trading_day
            and open_ist is not null and session_date < (now() at time zone 'Asia/Kolkata')::date""")).scalar()
        nxt = lambda d: q("""select min(session_date) from trading_session where is_trading_day
            and open_ist is not null and session_date > :d""", d=d)
        lab_next = (await nxt(lab)).scalar() if lab else None
        built_next = (await nxt(built)).scalar() if built else None
        print(lab, lab_next, built, built_next, prev)
asyncio.run(go())
PY
}

build() {  # FROM TO SHARDS
  local pids=() rc=0 i
  for ((i = 0; i < $3; i++)); do
    "${CLI[@]}" training build --dataset asif --from "$1" --to "$2" --shard "$i/$3" \
      --operator e51_data > "var/logs/daily/e51_build_${TODAY}_${i}.log" 2>&1 &
    pids+=($!)
  done
  for i in "${pids[@]}"; do wait "$i" || rc=1; done
  return $rc
}

case "${1:-}" in
  backfill)
    [[ $# -ge 3 ]] || { echo "usage: $0 backfill FROM TO [SHARDS]" >&2; exit 2; }
    say "E51_DATA_BACKFILL start ${2}..${3} shards=${4:-3}"
    build "$2" "$3" "${4:-3}" || fail "backfill build ${2}..${3} (see var/logs/daily/e51_build_${TODAY}_*.log)"
    say "E51_DATA_BACKFILL done ${2}..${3}"
    ;;
  daily)
    read -r LAB LAB_NEXT BUILT BUILT_NEXT PREV <<< "$(plan)" || fail "plan unreadable"
    say "E51_DATA plan labelled=${LAB} built=${BUILT} previous_session=${PREV}"
    if [[ "$LAB_NEXT" != None && ! "$LAB_NEXT" > "$PREV" ]]; then
      "${CLI[@]}" training labels-v2 --from "$LAB_NEXT" --to "$PREV" > "var/logs/daily/e51_labels_${TODAY}.json" 2>> "$LOG" \
        || fail "labels-v2 ${LAB_NEXT}..${PREV}"
      read -r LAB LAB_NEXT BUILT BUILT_NEXT PREV <<< "$(plan)"
      say "E51_DATA labels through ${LAB}"
    fi
    if [[ "$BUILT_NEXT" != None && ! "$BUILT_NEXT" > "$LAB" ]]; then
      build "$BUILT_NEXT" "$LAB" 1 || fail "dataset build ${BUILT_NEXT}..${LAB}"
      say "E51_DATA dataset through ${LAB}"
    fi
    "${CLI[@]}" training samples --dataset asif --labels label-v2 > "var/logs/daily/e51_samples_${TODAY}.json" 2>> "$LOG" \
      || fail "samples"
    say "E51_DATA_DONE $(.venv/bin/python -c "import json,sys; d=json.load(open(sys.argv[1])); print({k: d[k] for k in d if k in ('inserted','rows','build_sha256','snapshots')})" "var/logs/daily/e51_samples_${TODAY}.json" 2>/dev/null)"
    ;;
  *) echo "usage: $0 daily | backfill FROM TO [SHARDS]" >&2; exit 2 ;;
esac
