#!/bin/bash
# First-boot bootstrap: the application role and both databases.
#
# prajna_rw is deliberately unprivileged — no superuser, no CREATEDB, no
# CREATEROLE. It owns its two databases and nothing else, so it cannot reach a
# V1 database even if one were ever created in this cluster.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
     -v pw="$PRAJNA_RW_PASSWORD" <<'SQL'
CREATE ROLE prajna_rw LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'pw';
CREATE DATABASE prajna      OWNER prajna_rw;
CREATE DATABASE prajna_test OWNER prajna_rw;
-- No database in this cluster is connectable by default; owners get it back.
REVOKE CONNECT ON DATABASE postgres FROM PUBLIC;
SQL

for db in prajna prajna_test; do
  # btree_gist backs the SCD2 EXCLUDE constraint on instrument.
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$db" \
       -c "CREATE EXTENSION IF NOT EXISTS btree_gist;"
done
