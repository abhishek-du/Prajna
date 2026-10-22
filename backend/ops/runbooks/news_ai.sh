#!/usr/bin/env bash
# News AI enrichment (decision NEWS-CONTENT; enabled by the user 2026-10-22). Every 30 min:
# items of the last 48 h without an enrichment get one (AWS Bedrock Converse), stored in
# news_ai_enrichment with knowable_at = generated_at. Enrichment only, never a source fact;
# nothing in Stage 3/4 reads it yet. PAPER/RESEARCH only: no order is ever touched.
#
#   ops/runbooks/news_ai.sh
#
# Off unless .env has PRAJNA_NEWS_AI_ENABLED=true and PRAJNA_NEWS_AI_MODEL_ID (the command
# refuses, exit 3, no model call). The Bedrock API key is read from .env
# (AWS_BEARER_TOKEN_BEDROCK) into the environment only: never argv, never printed.
# Log: var/logs/daily/news_ai_<day>.log, one NEWS_AI line per run; Telegram when every
# call of a run failed (credentials, model access, quota).
set -uo pipefail
cd "$(dirname "$0")/../.."
mkdir -p var/logs/daily var/run
TODAY="$(TZ=Asia/Kolkata date +%F)"
LOG="var/logs/daily/news_ai_${TODAY}.log"
NOTIFY="${PRAJNA_TELEGRAM_CMD:-ops/runbooks/telegram_notify.sh}"
say() { echo "[$(TZ=Asia/Kolkata date '+%F %T IST')] $*" | tee -a "$LOG"; }
export PRAJNA_SUPPLIED_TOKEN="$(grep '^PRAJNA_WRITE_TOKEN=' .env 2>/dev/null | cut -d= -f2-)"
AWS_BEARER_TOKEN_BEDROCK="$(grep '^AWS_BEARER_TOKEN_BEDROCK=' .env 2>/dev/null | cut -d= -f2-)"
[[ -n "$AWS_BEARER_TOKEN_BEDROCK" ]] && export AWS_BEARER_TOKEN_BEDROCK

exec 9> var/run/news_ai.lock
if ! flock -n 9; then say "NEWS_AI_SKIP another run holds var/run/news_ai.lock"; exit 0; fi

OUT="var/logs/daily/news_ai_${TODAY}_last.json"
.venv/bin/python -m app.cli.main --plain news ai-enrich --commit > "$OUT" 2>> "$LOG"
rc=$?
line="$(.venv/bin/python - "$OUT" 2>/dev/null <<'PY' || grep -m1 -E '^REFUSED' "$OUT" || echo "output unreadable"
import json, sys
d = json.load(open(sys.argv[1]))
print(f"candidates={d['candidates']} stored={d['stored']} status={d['status']} "
      f"today_before={d['done_today_before']} errors={d['errors']}")
PY
)"
say "NEWS_AI rc=${rc} ${line}"
if [[ $rc -eq 0 ]] && .venv/bin/python - "$OUT" <<'PY' 2>/dev/null
import json, sys
d = json.load(open(sys.argv[1]))
sys.exit(0 if d["candidates"] and not d["status"].get("OK") and not d["status"].get("INVALID") else 1)
PY
then
  "$NOTIFY" "Prajna news AI ISSUE: every call failed: ${line:0:300}" >/dev/null 2>&1 || true
fi
[[ $rc -eq 3 ]] && exit 0          # disabled: not an error
exit "$rc"
