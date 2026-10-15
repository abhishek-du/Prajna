#!/usr/bin/env bash
# Send one Telegram message (user request 2026-10-15: backfill updates and issues).
#
#   ops/runbooks/telegram_notify.sh "<text>"        (or text on stdin)
#
# TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID come from .env and never appear in argv (curl
# reads its URL from stdin), so `ps` never shows the token. A send failure is logged
# and returns non-zero; it never blocks the caller's work.
set -uo pipefail
cd "$(dirname "$0")/../.."
TOKEN="$(grep '^TELEGRAM_BOT_TOKEN=' .env 2>/dev/null | cut -d= -f2-)"
CHAT="$(grep '^TELEGRAM_CHAT_ID=' .env 2>/dev/null | cut -d= -f2-)"
TEXT="${1:-$(cat)}"
mkdir -p var/logs/backfill
LOG=var/logs/backfill/telegram.log
if [[ -z "$TOKEN" || -z "$CHAT" ]]; then
  echo "[$(TZ=Asia/Kolkata date '+%F %T IST')] TELEGRAM_SKIPPED no credentials in .env" >> "$LOG"
  exit 2
fi
resp="$(printf 'url = "https://api.telegram.org/bot%s/sendMessage"\n' "$TOKEN" | \
  curl -sS -m 20 -K - --data-urlencode "chat_id=${CHAT}" \
       --data-urlencode "text=${TEXT:0:4000}" --data-urlencode "disable_web_page_preview=true" 2>&1)"
if grep -q '"ok":true' <<<"$resp"; then
  echo "[$(TZ=Asia/Kolkata date '+%F %T IST')] TELEGRAM_SENT ${#TEXT} chars" >> "$LOG"
else
  # never log the token: the response does not contain it, the URL is not printed
  echo "[$(TZ=Asia/Kolkata date '+%F %T IST')] TELEGRAM_FAILED ${resp:0:200}" >> "$LOG"
  exit 1
fi
