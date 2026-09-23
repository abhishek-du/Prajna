# prajna — AutoTrade Pro V2

Upstox-only, provenance-bearing market-data ingestion for NSE.

## Why this exists

A forensic audit of V1 ([docs/2026-09-22_PHASE_0_SYSTEM_DISCOVERY.md](docs/2026-09-22_PHASE_0_SYSTEM_DISCOVERY.md))
established that its 19 GB database stores observations without recording when
they became knowable or where they came from. The same trading session exists
under 14 timestamp anchors whose copies disagree on price; fundamentals history
is overwritten and gone; a research harness writes into the live
trade-authorization table.

V2 starts at Stage 1 (Data Ingestion) because that is where all of it originates.

## Non-negotiable constraints

1. **Upstox only** for market/trading data. No Zerodha/Kite, no yfinance, no
   Kite instrument tokens. V1 is read for config discovery and proven behavior;
   V2 never imports V1 runtime config.
2. Separate database `prajna` + role `prajna_rw`. The app **fails closed** if
   `DATABASE_URL` points at `autotrade_pro`.
3. Raw vendor bytes archived **before** parsing. Parsers are pure: no network, no DB.
4. Every row carries `source`, `run_id`, `payload_sha256`, `fetched_at`, `knowable_at`.
5. Append-only. Fundamentals are snapshots; instrument identity is SCD2.
6. `knowable_at` is never invented — unverifiable cases get the conservative
   bound and `knowable_at_verified = false`.
7. CLI defaults to `--dry-run`; writes need `--commit` **and** a write token.
8. Fail loud: a dropped row writes an `ingest_anomaly` and fails the run.

## Quick start

PostgreSQL runs in Docker (`backend/ops/docker/compose.yml`, `postgres:18`,
loopback-only on 127.0.0.1:5432, data in the `prajna_pgdata` volume). Its
secrets live in `backend/ops/docker/.env` (gitignored): `POSTGRES_PASSWORD` and
`PRAJNA_RW_PASSWORD`, which must match the password in `PRAJNA_DATABASE_URL`.
The init script creates `prajna_rw`, `prajna`, `prajna_test` and btree_gist on
first boot of an empty volume.

```bash
cd backend/ops/docker && docker compose up -d --wait && cd ../..
```

```bash
cd backend
cp .env.example .env            # fill in Upstox credentials + DSNs
.venv/bin/python -m app.cli.main db check-isolation
.venv/bin/python -m app.cli.main db upgrade
.venv/bin/python -m app.cli.main db status
.venv/bin/python -m pytest      # network blocked, test DB enforced
```

## Milestones

| M | Scope | State |
|---|---|---|
| M0 | Foundation: isolation, migrations, contracts, provenance, archive, tests | **done** |
| M1 | Upstox pre-open capture (WebSocket v3) | next — blocked on B0 (token) |
| M2 | Session calendar | |
| M3 | Instrument master (SCD2) | |
| M4 | Market data + `knowable_at` measurement (B1/B2) | |
| M5 | Corporate actions | |
| M6 | Macro / indices / flows | |
| M7 | Fundamentals + news | |

## Inspecting the database

There is no `psql` on this host, so the CLI is the query surface.

```bash
cd /home/cis/windows/prajna/backend

.venv/bin/python -m app.cli.main db status            # rows + provenance coverage
.venv/bin/python -m app.cli.main db tables            # tables, row estimates, size
.venv/bin/python -m app.cli.main db describe preopen_tick
.venv/bin/python -m app.cli.main db sql "select * from ingest_run order by started_at desc"
.venv/bin/python -m app.cli.main db current           # alembic revision
.venv/bin/python -m app.cli.main db check-isolation   # prove we are not on V1
```

`db sql` opens a **READ ONLY** transaction — Postgres rejects any write, so a
typo cannot damage data. Pass `--allow-write` only when you mean it.

### Web viewer

```bash
.venv/bin/python -m app.cli.main db web          # http://127.0.0.1:8081
```

Grouped table list with live row counts, row browser, column and constraint
inspector, and an ad-hoc SQL box. Every query runs inside
`SET TRANSACTION READ ONLY` and it binds to loopback only, because it holds
database credentials.

Port 8081, not 8080 — 8080 is already served by another (PHP) application on
this host. Override with `--port`.

### External GUI (DBeaver, pgAdmin, TablePlus)

```
host     localhost      port 5432
database prajna         user prajna_rw
password see PRAJNA_DATABASE_URL in backend/.env
```

`prajna_rw` has **no privileges on `autotrade_pro`** — connecting with it cannot
read or write V1. To inspect V1, use the `autotrade` credentials from
`auto-trade-pro/autotrade-backend/.env` and keep it read-only.

### Installing a psql client (optional)

```bash
sudo apt install postgresql-client     # needs your sudo password
psql "$(grep ^PRAJNA_DATABASE_URL backend/.env | cut -d= -f2- | sed 's/+asyncpg//')"
```
