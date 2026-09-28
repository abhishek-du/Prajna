#!/usr/bin/env bash
# Stage 3 feature snapshot for TODAY's session (IST). Decision SCHEDULE is
# APPROVED (2026-09-28, PRE_OPEN option B: --after-replay); the cron lines in
# ops/cron/prajna.cron stay commented (APPROVED_NOT_INSTALLED) until the first
# production run is authorised (docs/STAGE_3_PRODUCTION_SCHEDULE.md).
#
#   ops/runbooks/stage3_snapshot.sh PRE_SESSION|PRE_OPEN [--token-from-dotenv] [--after-replay]
#
# - One run at a time: flock on var/run/stage3.lock. A start while another run
#   holds it waits up to STAGE3_LOCK_WAIT seconds (default 300: PRE_OPEN waits for
#   a slow PRE_SESSION instead of being lost), then exits 1 with marker
#   STAGE3_SKIP and writes nothing.
# - Calls ONLY the lock-checked command `prajna stage3 run --commit`: every run
#   re-checks Stage 1, Stage 2, the kill switch, PRAJNA_STAGE3_ENABLED, the
#   decisions, the registry and the token; a refusal exits 3, is audited in
#   stage3_event and writes nothing (marker STAGE3_REFUSED). There is no bypass.
# - The token travels in the environment only (PRAJNA_SUPPLIED_TOKEN), never in
#   argv, and is never printed. Without --token-from-dotenv the caller's
#   environment must already hold it (otherwise the lock check refuses). With it,
#   it is read from .env at run time exactly as maintenance.sh does.
# - A non-trading day (or a session without a pre-open window) is skipped by the
#   command itself ("skipped" in its JSON).
# - Completion after 09:15 IST is marked STAGE3_LATE: the values stay point in
#   time (as_of is fixed by the snapshot, not by the clock), only availability
#   was late; feature_value.computed_at records when.
# - --after-replay (PRE_OPEN): today's pre-open ticks reach the database only when
#   preopen_day.sh replays its capture (measured 09:20-09:33). Wait up to
#   STAGE3_REPLAY_WAIT seconds (default 2400) for "replay exit 0" in its log; a
#   failed replay or a timeout skips the run (STAGE3_SKIP, nothing written): a
#   snapshot is never computed on a partly replayed pre-open.
set -uo pipefail
USAGE="usage: $0 PRE_SESSION|PRE_OPEN [--token-from-dotenv] [--after-replay]"
KIND="${1:-}"
[[ "$KIND" == PRE_SESSION || "$KIND" == PRE_OPEN ]] || { echo "$USAGE" >&2; exit 2; }
shift
DOTENV=0 REPLAY=0
for a in "$@"; do
  case "$a" in
    --token-from-dotenv) DOTENV=1 ;;
    --after-replay) REPLAY=1 ;;
    *) echo "$USAGE" >&2; exit 2 ;;
  esac
done
cd "$(dirname "$0")/../.."
mkdir -p var/logs/daily var/run
TODAY="$(TZ=Asia/Kolkata date +%F)"
exec > >(tee -a "var/logs/daily/stage3_${TODAY}.log") 2>&1
say() { echo "[$(TZ=Asia/Kolkata date '+%F %T IST')] $*"; }
if [[ $DOTENV == 1 ]]; then
  PRAJNA_SUPPLIED_TOKEN="$(grep '^PRAJNA_WRITE_TOKEN=' .env | cut -d= -f2-)"
  export PRAJNA_SUPPLIED_TOKEN
fi

if [[ $REPLAY == 1 ]]; then
  PLOG="var/logs/preopen_${TODAY}.log"
  deadline=$(( $(date +%s) + ${STAGE3_REPLAY_WAIT:-2400} ))
  until grep -q "replay exit" "$PLOG" 2>/dev/null; do
    if (( $(date +%s) >= deadline )); then
      say "STAGE3_SKIP ${KIND} ${TODAY}: no pre-open replay result in ${PLOG}; nothing written"
      exit 1
    fi
    sleep 20
  done
  if ! grep -q "replay exit 0" "$PLOG"; then
    say "STAGE3_SKIP ${KIND} ${TODAY}: pre-open replay failed ($(grep -o 'replay exit [0-9]*' \
        "$PLOG" | tail -1)); nothing written"
    exit 1
  fi
fi

exec 9> var/run/stage3.lock
if ! flock -w "${STAGE3_LOCK_WAIT:-300}" 9; then
  say "STAGE3_SKIP ${KIND} ${TODAY}: another Stage 3 run held var/run/stage3.lock for" \
      "${STAGE3_LOCK_WAIT:-300} s"
  exit 1
fi

say "STAGE3_START ${KIND} ${TODAY}"
out="var/logs/daily/stage3_${TODAY}_${KIND}.json"
.venv/bin/python -m app.cli.main --plain stage3 run --session "$TODAY" --snapshot "$KIND" \
  --commit > "$out" 2>/dev/null
rc=$?
summ() {  # one line per snapshot from the command's JSON output
  .venv/bin/python - "$1" <<'EOF' 2>/dev/null || echo "output unreadable: $1"
import json, sys
for r in json.load(open(sys.argv[1])):
    print(r.get("skipped") or " ".join(f"{k}={r.get(k)}" for k in (
        "run_id", "rows", "inserted", "already_present", "seconds")))
EOF
}
case $rc in
  0) say "STAGE3_DONE ${KIND} ${TODAY} $(summ "$out")" ;;
  3) say "STAGE3_REFUSED ${KIND} ${TODAY}: locked (audited in stage3_event); nothing written"
     grep -E '^(PASS|FAIL) ' "$out" | sed 's/^/    /' ;;
  *) say "STAGE3_FAILED ${KIND} ${TODAY} rc=${rc}: the run is FAILED and rolled back; see $out" ;;
esac
if [[ $rc == 0 && "$(TZ=Asia/Kolkata date +%H%M)" > 0915 ]] && grep -q '"run_id"' "$out"; then
  say "STAGE3_LATE ${KIND} ${TODAY}: completed after 09:15 IST (values remain point in time)"
fi
exit $rc
