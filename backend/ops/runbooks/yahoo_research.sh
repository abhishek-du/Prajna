#!/usr/bin/env bash
# Research-only Yahoo Finance analyst snapshot (user approval 2026-10-23). Not a production
# source: no database write, read by no stage or model. See ops/research/yahoo_consensus.py.
#   Mon-Fri 18:20: the covered names only (coverage.json).
#   Saturday 10:20: the full liquid universe (median traded value >= Rs 5 cr), which also
#   refreshes coverage.json. The first run is always full.
set -uo pipefail
cd "$(dirname "$0")/../.."
PY=.venv-research/bin/python
export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt   # TLS here is re-signed; system CA bundle
OUT=var/research/yahoo
DAY="$(TZ=Asia/Kolkata date +%F)"
LOG="var/logs/daily/yahoo_research_${DAY}.log"
mkdir -p "$OUT" var/logs/daily var/run
say() { echo "[$(TZ=Asia/Kolkata date '+%F %T IST')] $*" | tee -a "$LOG"; }
exec 9> var/run/yahoo_research.lock
flock -n 9 || { say "YAHOO_RESEARCH_SKIP another run holds the lock"; exit 0; }
[[ -x "$PY" ]] || { say "YAHOO_RESEARCH_FAIL research venv missing ($PY)"; exit 1; }

UNI="$OUT/universe_${DAY}.csv"
docker exec prajna-postgres sh -c 'psql -U "$POSTGRES_USER" -d prajna -At -F, -c "
with b as (select instrument_key, close*volume tv, row_number() over (partition by
  instrument_key order by market_date desc) rn from canon_market_bar where timeframe = '"'"'1d'"'"'
  and instrument_key like '"'"'NSE_EQ|%'"'"' and market_date > current_date - 45),
m as (select instrument_key, percentile_cont(0.5) within group (order by tv) med from b
  where rn <= 20 group by 1)
select i.trading_symbol, i.instrument_key from m join instrument i using (instrument_key)
where i.valid_to = '"'"'infinity'"'"' and i.lifecycle_status = '"'"'ACTIVE'"'"' and m.med >= 5e7
order by m.med desc"' > "$UNI.body" || { say "YAHOO_RESEARCH_FAIL universe query"; exit 1; }
{ echo "symbol,instrument_key"; cat "$UNI.body"; } > "$UNI" && rm -f "$UNI.body"

ARGS=()
if [[ "$(TZ=Asia/Kolkata date +%u)" != "6" && -s "$OUT/coverage.json" ]]; then
  ARGS=(--only-covered "$OUT/coverage.json")
fi
say "YAHOO_RESEARCH_START universe=$(($(wc -l < "$UNI") - 1)) mode=${ARGS:+covered}${ARGS:-full}"
"$PY" ops/research/yahoo_consensus.py "$UNI" "$OUT" "${ARGS[@]}" >> "$LOG" 2>&1
rc=$?
say "YAHOO_RESEARCH_DONE rc=$rc $(tail -1 "$LOG" | cut -c1-300)"
exit $rc
