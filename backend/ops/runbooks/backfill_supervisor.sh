#!/usr/bin/env bash
# Backfill supervisor (approved 2026-10-15): keeps the approved Stage 1 intraday
# backfill running night after night until it is complete, resolves the KNOWN
# failure classes itself, and reports everything else. Deterministic; cron calls it
# every 15 minutes (ops/cron/prajna.cron). One invocation = one decision, then exit.
#
#   ops/runbooks/backfill_supervisor.sh [tick|status|report]
#
# tick (default):
#   0 var/run/backfill.paused exists      -> SUPERVISOR_PAUSED, nothing else
#   1 var/run/backfill.done exists        -> SUPERVISOR_DONE, nothing else
#   2 storage rule (pre-approved): free < ARCHIVE_BELOW_GB (75) -> move the OLDEST
#     backup dumps (+ .sha256) to the archive dir (another filesystem), verifying the
#     sha256 after the copy, never touching the newest KEEP_BACKUPS (2); stop as soon
#     as free >= ARCHIVE_BELOW_GB. Never deletes anything else. No archive dir or
#     not writable -> SUPERVISOR_ALERT storage_archive_unavailable
#   3 a backfill is already running (backfill.sh process) -> SUPERVISOR_RUNNING
#   4 trading day 06:30-16:00 IST -> SUPERVISOR_WINDOW_CLOSED (backfill.sh refuses
#     06:50-16:00 itself; 06:30 leaves room for the morning jobs)
#   5 free < GUARD_GB (60)        -> SUPERVISOR_ALERT disk_below_guard (no start)
#   6 the candles lock is free    -> start backfill.sh --login --stages <STAGES>
#     detached (fraction 0.5), log SUPERVISOR_STARTED; the lock busy (the close or
#     morning job) -> SUPERVISOR_WAITING_LOCK
#   The previous run's last BACKFILL_COMPLETED line decides: all_stages_complete ->
#   backfill.done (a --stages subset never ends it); time limit, window, lock or a
#   subset completion -> resumed by the next tick; disk_low, token and vendor stops ->
#   SUPERVISOR_ALERT and resumed; anything unrecognised -> SUPERVISOR_ALERT
#   unknown_stop:<status> (the AI agent diagnoses it: ops/agents/backfill_agent.sh).
# status:  one JSON line (state, free GB, last run status, stage progress)
# report:  the morning report var/logs/backfill/report_<date>.json
#
# Test hooks: PRAJNA_RUNBOOK_DIR, PRAJNA_TEST_NOW_HHMM, PRAJNA_TEST_FREE_GB,
# PRAJNA_TEST_TRADING_DAY (true|false), PRAJNA_BACKUP_DIR, PRAJNA_BACKUP_ARCHIVE_DIR.
set -uo pipefail

cd "$(dirname "$0")/../.."
RB="${PRAJNA_RUNBOOK_DIR:-ops/runbooks}"
# phase 1 = 1h + 15m first (user 2026-10-15: "1h and 15m ASAP"); phase 2 = all three
# (1h/15m resume as no-ops from their checkpoints, then 1m), which alone can end it
PHASE1_STAGES="1h,15m"
if [[ -n "${PRAJNA_BACKFILL_STAGES:-}" ]]; then STAGES="$PRAJNA_BACKFILL_STAGES"
elif [[ -f var/run/backfill.phase1_done ]]; then STAGES="1h,1m,15m"
else STAGES="$PHASE1_STAGES"; fi
FAST_FRACTION="${PRAJNA_BACKFILL_FAST_FRACTION:-0.9}"     # alone on the historical API
SHARED_FRACTION="${PRAJNA_BACKFILL_SHARED_FRACTION:-0.5}" # another Upstox job running
ARCHIVE_BELOW_GB="${PRAJNA_ARCHIVE_BELOW_GB:-75}"
GUARD_GB="${PRAJNA_BACKFILL_MIN_FREE_GB:-60}"
KEEP_BACKUPS="${PRAJNA_KEEP_BACKUPS:-2}"
BACKUPS="${PRAJNA_BACKUP_DIR:-var/backups}"
ARCHIVE="${PRAJNA_BACKUP_ARCHIVE_DIR:-/windows/prajna_archive}"
LOCK="${PRAJNA_CANDLES_LOCK:-var/run/candles.lock}"
mkdir -p var/run var/logs/backfill
LOG=var/logs/backfill/supervisor.log
say() { echo "[$(TZ=Asia/Kolkata date '+%F %T IST')] $*" | tee -a "$LOG"; }

free_gb() {
  if [[ -n "${PRAJNA_TEST_FREE_GB:-}" ]]; then echo "$PRAJNA_TEST_FREE_GB"; return; fi
  df -BG --output=avail . | tail -1 | tr -dc '0-9'
}
now_hhmm() { echo "${PRAJNA_TEST_NOW_HHMM:-$(TZ=Asia/Kolkata date +%H%M)}"; }
trading_day() {
  if [[ -n "${PRAJNA_TEST_TRADING_DAY:-}" ]]; then echo "$PRAJNA_TEST_TRADING_DAY"; return; fi
  .venv/bin/python -m app.cli.main --plain db sql "select is_trading_day from trading_session \
    where session_date = '$(TZ=Asia/Kolkata date +%F)'" 2>/dev/null | sed -n 3p | tr -d ' ' \
    | sed 's/^t$/true/; s/^f$/false/'
}
running() { pgrep -f "${RB}/backfill.sh --login --stages" >/dev/null 2>&1; }
process_state() {   # running = backfill.sh itself; queued = only its flock wrapper waiting
  if pgrep -f "^(/usr/bin/env )?bash ${RB}/backfill.sh --login" >/dev/null 2>&1 || \
     pgrep -f "^/bin/bash ${RB}/backfill.sh --login" >/dev/null 2>&1; then echo running
  elif running; then echo queued
  else echo none; fi
}
last_completed() {
  local f
  f="$(ls -1t var/logs/backfill/backfill_*.log 2>/dev/null | head -1)"
  [[ -n "$f" ]] && grep -h "BACKFILL_COMPLETED" "$f" | tail -1 | sed 's/.*status=//'
}

other_upstox_job() {   # any other runbook that calls the Upstox REST API right now
  [[ -n "${PRAJNA_TEST_OTHER_JOB:-}" ]] && { [[ "$PRAJNA_TEST_OTHER_JOB" == "true" ]]; return; }
  pgrep -f "daily.sh --login (weekly|monthly|morning|refresh)|preopen_day.sh|global_refresh.sh" \
    >/dev/null 2>&1
}

archive_oldest() {   # the pre-approved storage rule
  local free target dumps n
  free="$(free_gb)"
  (( free >= ARCHIVE_BELOW_GB )) && return 0
  if [[ ! -d "$ARCHIVE" || ! -w "$ARCHIVE" ]]; then
    say "SUPERVISOR_ALERT storage_archive_unavailable dir=$ARCHIVE free_gb=$free"; return 1
  fi
  mapfile -t dumps < <(ls -1tr "$BACKUPS"/*.dump 2>/dev/null)
  n=${#dumps[@]}
  for (( i = 0; i < n - KEEP_BACKUPS; i++ )); do
    free="$(free_gb)"
    (( free >= ARCHIVE_BELOW_GB )) && break
    target="$ARCHIVE/$(basename "${dumps[$i]}")"
    cp -p "${dumps[$i]}" "$target" || { say "SUPERVISOR_ALERT archive_copy_failed ${dumps[$i]}"; return 1; }
    if [[ "$(sha256sum < "${dumps[$i]}" | cut -d' ' -f1)" != "$(sha256sum < "$target" | cut -d' ' -f1)" ]]; then
      rm -f "$target"; say "SUPERVISOR_ALERT archive_sha_mismatch ${dumps[$i]}"; return 1
    fi
    [[ -f "${dumps[$i]}.sha256" ]] && cp -p "${dumps[$i]}.sha256" "$ARCHIVE/"
    rm -f "${dumps[$i]}" "${dumps[$i]}.sha256"
    say "SUPERVISOR_ARCHIVED $(basename "${dumps[$i]}") -> $ARCHIVE (sha256 verified)"
    [[ -n "${PRAJNA_TEST_FREE_GB:-}" ]] && PRAJNA_TEST_FREE_GB=$(( PRAJNA_TEST_FREE_GB + 5 ))
  done
  return 0
}

status_json() {
  local last; last="$(last_completed)"
  printf '{"paused":%s,"done":%s,"running":%s,"process":"%s","free_gb":%s,"last_status":"%s","stages":"%s"}\n' \
    "$([[ -f var/run/backfill.paused ]] && echo true || echo false)" \
    "$([[ -f var/run/backfill.done ]] && echo true || echo false)" \
    "$(running && echo true || echo false)" "$(process_state)" "$(free_gb)" "${last:-none}" "$STAGES"
}

tick() {
  if [[ -f var/run/backfill.paused ]]; then say "SUPERVISOR_PAUSED"; return 0; fi
  if [[ -f var/run/backfill.done ]]; then say "SUPERVISOR_DONE"; return 0; fi
  local last; last="$(last_completed)"
  case "${last:-none}" in
    all_stages_complete*)                  # only a run of ALL three stages ends it
      touch var/run/backfill.done; say "SUPERVISOR_DONE all stages complete"; return 0 ;;
    selected_stages_complete*)               # only a run of exactly 1h,15m ends phase 1
      if [[ "$STAGES" == "$PHASE1_STAGES" ]] && grep -q "selected stages (${PHASE1_STAGES}) complete" \
           "$(ls -1t var/logs/backfill/backfill_*.log 2>/dev/null | head -1)" 2>/dev/null; then
        touch var/run/backfill.phase1_done; STAGES="1h,1m,15m"
        say "SUPERVISOR_PHASE1_DONE 1h and 15m complete; phase 2 adds 1m"
      fi ;;
    none|started*|time_limit_resumable*|time_window_over*|selected_stages_complete*|\
    another_candles_job_running*|refused_trading_hours*|plan_only*) ;;   # known, resumable
    disk_low*) say "SUPERVISOR_ALERT disk_low (backfill stopped itself; storage rule applies)" ;;
    token_invalid*|relogin_failed*) say "SUPERVISOR_ALERT token:${last} (next tick retries with --login)" ;;
    stage_*_not_complete*) say "SUPERVISOR_ALERT vendor_stop:${last} (resumable; agent reviews)" ;;
    *) say "SUPERVISOR_ALERT unknown_stop:${last}" ;;
  esac
  archive_oldest
  if running; then say "SUPERVISOR_RUNNING free_gb=$(free_gb)"; return 0; fi
  local hhmm td; hhmm="$(now_hhmm)"; td="$(trading_day)"
  if [[ "$td" == "true" && ! "$hhmm" < "0630" && "$hhmm" < "1600" ]]; then
    say "SUPERVISOR_WINDOW_CLOSED"; return 0
  fi
  if (( $(free_gb) < GUARD_GB )); then
    say "SUPERVISOR_ALERT disk_below_guard free_gb=$(free_gb) guard=$GUARD_GB"; return 0
  fi
  if ! flock -n "$LOCK" true 2>/dev/null; then say "SUPERVISOR_WAITING_LOCK"; return 0; fi
  local frac until dow
  frac="$FAST_FRACTION"; until="06:50"
  dow="${PRAJNA_TEST_DOW:-$(TZ=Asia/Kolkata date +%u)}"     # 6 = Saturday
  if other_upstox_job; then frac="$SHARED_FRACTION"; fi
  # Saturday 10:00 weekly corporate-action sweep (fraction 0.3): stop the fast run at
  # 09:50, run the shared fraction until 13:00, then fast again
  if [[ "$dow" == "6" && "$hhmm" < "0950" ]]; then until="09:50"
  elif [[ "$dow" == "6" && "$hhmm" < "1300" ]]; then frac="$SHARED_FRACTION"; until="13:00"; fi
  nohup flock -n "$LOCK" env PRAJNA_UPSTOX_RATE_FRACTION="$frac" \
    "$RB/backfill.sh" --login --stages "$STAGES" --until "$until" \
    >> var/logs/backfill/supervisor_child.log 2>&1 &
  say "SUPERVISOR_STARTED stages=$STAGES fraction=$frac until=$until free_gb=$(free_gb) pid=$!"
}

case "${1:-tick}" in
  tick) tick ;;
  status) status_json ;;
  report)
    out="var/logs/backfill/report_$(TZ=Asia/Kolkata date +%F).json"
    { status_json; grep -h "BACKFILL_PROGRESS" var/logs/backfill/backfill_*.log 2>/dev/null | tail -6; \
      grep -h "SUPERVISOR_ALERT" "$LOG" 2>/dev/null | tail -10; } > "$out"
    say "SUPERVISOR_REPORT $out" ;;
  *) echo "usage: $0 [tick|status|report]" >&2; exit 2 ;;
esac
