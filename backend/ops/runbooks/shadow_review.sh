#!/usr/bin/env bash
# Stage 4 v2 P2 LLM reviewer (docs/STAGE4_P2_REVIEWER_PREREGISTRATION.md): every P1 shadow
# trade not yet reviewed gets one outcome-blind review (AWS Bedrock, pinned model,
# temperature 0), stored in llm_review. SHADOW ONLY: no order is ever touched; the
# verdicts are measured at the P1 looks only.
#
#   ops/runbooks/shadow_review.sh [--no-telegram]
#
# Cron (weekdays 22:15 IST, after shadow_daily.sh at 21:30):
#   15 22 * * 1-5  cd $B && ops/runbooks/shadow_review.sh >> var/logs/cron.log 2>&1
# The Bedrock API key is read from .env (AWS_BEARER_TOKEN_BEDROCK) into the environment
# only: never argv, never printed. Telegram on a refusal or when every call failed.
set -uo pipefail
cd "$(dirname "$0")/../.."
P="${PRAJNA_PY:-.venv/bin/python}"
NOTIFY="${PRAJNA_TELEGRAM_CMD:-ops/runbooks/telegram_notify.sh}"
SEND=1; [[ "${1:-}" == "--no-telegram" ]] && SEND=0
mkdir -p var/logs/shadow var/run
DAY="$(TZ=Asia/Kolkata date +%F)"; OUT="var/logs/shadow/review_${DAY}.json"
say() { echo "[$(TZ=Asia/Kolkata date '+%F %T IST')] $*"; }
exec 9> var/run/shadow_review.lock
flock -n 9 || { say "SHADOW_REVIEW_SKIP another reviewer holds var/run/shadow_review.lock"; exit 0; }
AWS_BEARER_TOKEN_BEDROCK="$(grep '^AWS_BEARER_TOKEN_BEDROCK=' .env 2>/dev/null | cut -d= -f2-)"
if [[ -z "$AWS_BEARER_TOKEN_BEDROCK" ]]; then
  say "SHADOW_REVIEW_SKIP no Bedrock key in .env; no model call"; exit 0
fi
export AWS_BEARER_TOKEN_BEDROCK
export PRAJNA_SUPPLIED_TOKEN="$(grep '^PRAJNA_WRITE_TOKEN=' .env 2>/dev/null | cut -d= -f2-)"
say "SHADOW_REVIEW_START"
if "$P" -m app.cli.main --plain shadow review --commit > "$OUT" 2>&1; then
  rc=0
  mix="$(tr -d '\n ' < "$OUT" | grep -o '"mix":{[^}]*}' | head -1)"
  say "SHADOW_REVIEW_OK $(grep -o '"reviewed": [0-9]*' "$OUT") ${mix}"
  if grep -q '"reviewed": [1-9]' "$OUT" && ! grep -q '"OK:' "$OUT"; then
    rc=1; say "SHADOW_REVIEW_ALERT every call failed"
    (( SEND )) && "$NOTIFY" "Prajna SHADOW reviewer: every model call failed (key, access or quota)" >/dev/null 2>&1
  fi
else
  rc=1; why="$(grep -m1 REFUSED "$OUT" | cut -c1-300)"
  say "SHADOW_REVIEW_ALERT ${why:-failed (see ${OUT})}"
  (( SEND )) && "$NOTIFY" "Prajna SHADOW reviewer ISSUE: ${why:-failed}" >/dev/null 2>&1
fi
unset PRAJNA_SUPPLIED_TOKEN AWS_BEARER_TOKEN_BEDROCK
say "SHADOW_REVIEW_DONE rc=${rc}"
exit "$rc"
