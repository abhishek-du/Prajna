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
