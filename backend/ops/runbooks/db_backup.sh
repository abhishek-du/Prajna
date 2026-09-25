#!/usr/bin/env bash
# Verified backup of the prajna database, taken before every migration or
# data mutation (hardening plan, operating rules).
#
#   ops/runbooks/db_backup.sh [--label NAME] [--verify-counts] [--trial-restore]
#
# 1 pg_dump -Fc          -> var/backups/prajna_<IST stamp>_<label>.dump
# 2 pg_restore --list     the archive is readable; table-of-contents count
# 3 sha256                recorded next to the dump (.sha256)
# 4 --verify-counts       extract every table's data block from the dump
#                         (pg_restore -a) and compare its exact row count with
#                         the live table (run while no job writes)
# 5 --trial-restore       restore into a scratch database prajna_restore_check
#                         and compare row counts; needs a role with CREATEDB
#                         (the application role prajna_rw deliberately has none)
# The DSN is read from the application settings inside Python and passed to
# the tools through the environment; credentials are never printed.
set -euo pipefail

LABEL="manual"; TRIAL=0; COUNTS=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --label) LABEL="$2"; shift 2 ;;
    --trial-restore) TRIAL=1; shift ;;
    --verify-counts) COUNTS=1; shift ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
done

cd "$(dirname "$0")/../.."
P=.venv/bin/python
mkdir -p var/backups
chmod 700 var/backups
STAMP="$(TZ=Asia/Kolkata date +%Y%m%dT%H%M)"
OUT="var/backups/prajna_${STAMP}_${LABEL}.dump"
say() { echo "[$(TZ=Asia/Kolkata date '+%F %T IST')] $*"; }

# libpq environment from the configured DSN (never echoed)
eval "$("$P" - <<'EOF'
from urllib.parse import urlsplit, unquote
from app.core.config import get_settings
u = urlsplit(get_settings().PRAJNA_DATABASE_URL.replace("+asyncpg", ""))
import shlex
for k, v in (("PGHOST", u.hostname), ("PGPORT", u.port or 5432), ("PGUSER", unquote(u.username or "")),
             ("PGPASSWORD", unquote(u.password or "")), ("PGDATABASE", u.path.lstrip("/"))):
    print(f"export {k}={shlex.quote(str(v))}")
EOF
)"
[[ "$PGDATABASE" == "prajna" ]] || { say "ABORT: target database is '$PGDATABASE', not prajna"; exit 3; }

say "BACKUP_STARTED db=${PGDATABASE} out=${OUT}"
pg_dump -Fc --no-owner --no-privileges -f "$OUT"
chmod 600 "$OUT"
toc=$(pg_restore --list "$OUT" | grep -c ';' || true)
sha=$(sha256sum "$OUT" | cut -d' ' -f1)
echo "$sha  $(basename "$OUT")" > "${OUT}.sha256"
size=$(du -h "$OUT" | cut -f1)
say "BACKUP_WRITTEN size=${size} toc_entries=${toc} sha256=${sha}"

if [[ $COUNTS -eq 1 ]]; then
  bad=0; n=0
  for t in $(psql -At -c "select table_name from information_schema.tables where table_schema='public' and table_type='BASE TABLE' order by 1"); do
    live=$(psql -At -c "select count(*) from \"$t\"")
    dumped=$(pg_restore -a -t "$t" -f - "$OUT" | awk '/^COPY /{on=1; next} /^\\\.$/{on=0} on{c++} END{print c+0}')
    n=$((n+1))
    if [[ "$live" != "$dumped" ]]; then bad=$((bad+1)); say "COUNT_MISMATCH ${t} live=${live} dump=${dumped}"; fi
  done
  if [[ $bad -eq 0 ]]; then say "COUNTS_VERIFIED tables=${n} (dump row counts == live row counts)"
  else say "COUNTS_MISMATCH tables=${bad}/${n}"; exit 4; fi
fi

if [[ $TRIAL -eq 1 ]]; then
  SCRATCH=prajna_restore_check
  psql -q -d postgres -c "drop database if exists ${SCRATCH}" -c "create database ${SCRATCH}"
  pg_restore --no-owner --no-privileges -d "$SCRATCH" "$OUT"
  q="select string_agg(t || '=' || n, ',' order by t) from (select relname t, n_live_tup n from pg_stat_user_tables) x"
  cmp="select string_agg(format('%s=%s', table_name, (xpath('/row/c/text()', query_to_xml(format('select count(*) as c from %I', table_name), false, true, '')))[1]::text), ',' order by table_name) from information_schema.tables where table_schema='public' and table_type='BASE TABLE'"
  src=$(psql -At -d "$PGDATABASE" -c "$cmp")
  dst=$(psql -At -d "$SCRATCH" -c "$cmp")
  psql -q -d postgres -c "drop database ${SCRATCH}"
  if [[ "$src" == "$dst" ]]; then
    say "TRIAL_RESTORE_OK tables=$(tr ',' '\n' <<<"$src" | wc -l) (exact row counts identical)"
  else
    say "TRIAL_RESTORE_MISMATCH"; diff <(tr ',' '\n' <<<"$src") <(tr ',' '\n' <<<"$dst") || true; exit 4
  fi
fi
say "BACKUP_VERIFIED ${OUT}"
