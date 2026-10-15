#!/usr/bin/env bash
# Daily corporate-action refresh, option D1 (docs/STAGE1_DAILY_CA_REFRESH_PLAN.md,
# approved by the user 2026-10-15).
#
#   ops/runbooks/ca_refresh.sh targeted   # cron 06:45 Mon-Fri, candles lock, before the 07:00 1D
#   ops/runbooks/ca_refresh.sh rolling    # from close_then_backfill.sh, after the close
#   ops/runbooks/ca_refresh.sh selfheal   # cron 08:40 Mon-Fri, candles lock, after the morning 1D
#
# targeted  (a) bonus/split announcements (60 days) + (b) 1D DUPLICATE_KEY failures (3 days):
#           `ingest corporate-actions --isin ... --commit`; if anything was inserted,
#           `maintenance.sh derive` (after the 06:40 maintenance has finished)
# rolling   1/5 of all current NSE_EQ ISINs (weekday bucket), `--resume-hours 20`
# selfheal  today's 1D streams that FAILED with DUPLICATE_KEY (the OLIL signature), at most
#           MAX_KEYS: Telegram alert always; with PRAJNA_CA_SELF_HEAL=true, per key:
#           corporate actions for its ISIN, a bounded 1D re-ingest (last 14 days), then
#           `maintenance.sh derive`. A key still failing is an alert for the manual runbook.
#           All writes are the existing insert-only paths (D3 still refuses an unexplained
#           revision; nothing is overwritten).
#
# Log line: CA_REFRESH mode=... targeted=N inserted=K failed=F (var/logs/daily/ca_refresh_<day>.log).
# No login here: the 06:30 refresh holds the day's single TOTP login. Test hooks:
# PRAJNA_CLI, PRAJNA_PY, PRAJNA_TARGETS_JSON, PRAJNA_TELEGRAM_CMD, PRAJNA_MAINT_CMD.
set -uo pipefail
MODE="${1:-}"
cd "$(dirname "$0")/../.."
PY="${PRAJNA_PY:-.venv/bin/python}"
read -r -a CLI <<< "${PRAJNA_CLI:-.venv/bin/python -m app.cli.main --plain}"
NOTIFY="${PRAJNA_TELEGRAM_CMD:-ops/runbooks/telegram_notify.sh}"
MAINT="${PRAJNA_MAINT_CMD:-ops/runbooks/maintenance.sh}"
MAX_KEYS="${PRAJNA_CA_SELF_HEAL_MAX_KEYS:-10}"
mkdir -p var/logs/daily
TODAY="$(TZ=Asia/Kolkata date +%F)"
LOG="var/logs/daily/ca_refresh_${TODAY}.log"
say() { echo "[$(TZ=Asia/Kolkata date '+%F %T IST')] $*" | tee -a "$LOG"; }
alert() { say "CA_REFRESH_ALERT $*"; "$NOTIFY" "Prajna CA refresh ISSUE: $*" >/dev/null 2>&1 || true; }
# the write token travels in the environment, never in argv (visible to ps)
export PRAJNA_SUPPLIED_TOKEN="$(grep '^PRAJNA_WRITE_TOKEN=' .env 2>/dev/null | cut -d= -f2-)"

case "$MODE" in targeted|rolling|selfheal) ;; *) echo "usage: $0 targeted|rolling|selfheal" >&2; exit 2 ;; esac

field() {  # field <json> <name>: a list field, space separated
  "$PY" -c 'import json,sys; print(" ".join(json.loads(sys.argv[1])[sys.argv[2]]))' "$1" "$2"
}
summary() {  # summary <ingest json file>: "inserted=K failed=F"
  "$PY" - "$1" <<'EOF' 2>/dev/null || echo "inserted=? failed=? (unreadable output)"
import json, sys
d = json.load(open(sys.argv[1]))
f = d.get("failed") or 0
print(f"inserted={d.get('inserted') or 0} failed={len(f) if isinstance(f, list) else f}")
EOF
}

if [[ -n "${PRAJNA_TARGETS_JSON:-}" ]]; then T="$PRAJNA_TARGETS_JSON"
else T="$(PGOPTIONS='-c default_transaction_read_only=on' "$PY" ops/measure/ca_targets.py "$MODE")" || {
  alert "mode=${MODE} target selection failed"; exit 1; }
fi
read -r -a ISINS <<< "$(field "$T" isins)"
read -r -a KEYS <<< "$(field "$T" keys)"
OUT="var/logs/daily/ca_refresh_${TODAY}_${MODE}.json"

ca_ingest() {  # ca_ingest <out> [extra args] -- isins...: one CA ingest, returns its rc
  local out="$1"; shift
  local args=() x
  while [[ $# -gt 0 && "$1" != "--" ]]; do args+=("$1"); shift; done
  shift
  for x in "$@"; do args+=(--isin "$x"); done
  "${CLI[@]}" ingest corporate-actions "${args[@]}" --commit > "$out"
}

derive_after() {  # wait for a running maintenance.sh (06:40), then derive once
  local i
  for i in $(seq 1 60); do pgrep -f "maintenance.sh (all|derive)" >/dev/null 2>&1 || break; sleep 10; done
  "$MAINT" derive >/dev/null 2>&1 && say "CA_REFRESH derive OK" || alert "mode=${MODE} derive FAILED"
}

case "$MODE" in
  targeted|rolling)
    if [[ ${#ISINS[@]} -eq 0 ]]; then
      say "CA_REFRESH mode=${MODE} targeted=0 inserted=0 failed=0"; exit 0
    fi
    extra=(); [[ "$MODE" == rolling ]] && extra=(--resume-hours 20)
    ca_ingest "$OUT" "${extra[@]}" -- "${ISINS[@]}"; rc=$?
    s="$(summary "$OUT")"
    say "CA_REFRESH mode=${MODE} targeted=${#ISINS[@]} ${s} rc=${rc}"
    (( rc != 0 )) && alert "mode=${MODE} corporate-actions ingest rc=${rc} ${s}"
    if [[ "$s" =~ inserted=([0-9]+) ]] && (( BASH_REMATCH[1] > 0 )); then derive_after; fi
    exit "$rc" ;;
  selfheal)
    if [[ ${#KEYS[@]} -eq 0 ]]; then
      say "CA_REFRESH mode=selfheal failing=0 healed=0 still_failing=0"; exit 0
    fi
    if (( ${#KEYS[@]} > MAX_KEYS )); then
      alert "mode=selfheal ${#KEYS[@]} 1D streams FAILED with DUPLICATE_KEY (> ${MAX_KEYS}); not self-healing, manual runbook: ${KEYS[*]:0:10}"
      exit 1
    fi
    alert "mode=selfheal 1D FAILED with DUPLICATE_KEY today: ${KEYS[*]}"
    if [[ "${PRAJNA_CA_SELF_HEAL:-false}" != "true" ]]; then
      say "CA_REFRESH mode=selfheal failing=${#KEYS[@]} SELF_HEAL_DISABLED (PRAJNA_CA_SELF_HEAL!=true)"
      exit 1
    fi
    FROM="$(TZ=Asia/Kolkata date -d "${TODAY} -14 days" +%F)"
    TO="$(TZ=Asia/Kolkata date -d "${TODAY} -1 day" +%F)"
    healed=0; still=()
    for i in "${!KEYS[@]}"; do
      k="${KEYS[$i]}"; isin="${ISINS[$i]}"
      ca_ingest "var/logs/daily/ca_refresh_${TODAY}_selfheal_${isin}.json" -- "$isin"
      say "CA_SELFHEAL ${k} corporate_actions $(summary "var/logs/daily/ca_refresh_${TODAY}_selfheal_${isin}.json")"
      if "${CLI[@]}" ingest candles --timeframe 1d --from "$FROM" --to "$TO" --key "$k" --commit \
           > "var/logs/daily/ca_refresh_${TODAY}_selfheal_${isin}_1d.json"; then
        healed=$((healed + 1)); say "CA_SELFHEAL ${k} 1d COMPLETE"
      else
        still+=("$k"); say "CA_SELFHEAL ${k} 1d STILL_FAILING"
      fi
    done
    derive_after
    say "CA_REFRESH mode=selfheal failing=${#KEYS[@]} healed=${healed} still_failing=${#still[@]}"
    if [[ ${#still[@]} -gt 0 ]]; then
      alert "mode=selfheal still failing after self-heal (manual runbook, e.g. a new vendor convention): ${still[*]}"
      exit 1
    fi
    "$NOTIFY" "Prajna CA refresh: self-heal fixed ${healed} key(s): ${KEYS[*]}" >/dev/null 2>&1 || true
    exit 0 ;;
esac
