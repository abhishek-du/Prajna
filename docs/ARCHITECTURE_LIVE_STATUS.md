# Architecture status: what is live, snapshot, batch, historical, or not implemented

**Measured** on 2026-09-29 at about 15:10 IST, read-only, at HEAD `17c4617`.

**Evidence sources:**

- the installed crontab (`crontab -l`);
- `ingest_run`: 7-day COMPLETE/COMMIT counts and the last success per source family;
- row counts and data extents per table;
- the application package list and the database schema (41 tables).

**The diagram's items** come from:

- `docs/STAGE_1_STATUS_REPORT.md` §2: Stage 1 column 1, "Data sources", and column 2, "Ingestion & storage";
- `app/features/registry.py` `DIAGRAM`: Stage 3;
- `docs/STAGE_3_DESIGN.md`: Stages 4–8.

**Categories** (an item gets a category only from what runs and what is stored, never from code merely existing):

| Category | Meaning |
|---|---|
| **LIVE-INTRADAY** | updated in the database during the market session, repeatedly |
| **SNAPSHOT** | captured for a fixed daily instant or window |
| **DAILY-BATCH** | refreshed on a schedule outside the session (morning, after the close, or periodic). Its newest data is the previous session |
| **HISTORICAL** | depth stored once and not re-fetched |
| **DEFERRED** | built, and stopped by a recorded decision |
| **NOT IMPLEMENTED** | no running code path stores it |

## Stage 1: data sources

| Diagram item | Category | Evidence (direct) |
|---|---|---|
| Market data, daily (1D) | **DAILY-BATCH** + **HISTORICAL** | Cron 07:00 Mon–Fri (previous session). `ohlcv_bar` 1d: 3,667,860 bars, 2020-01-01 → **2026-09-28**. 17,831 COMPLETE runs in 7 days (the historical endpoint, including global) |
| Market data, intraday 1m / 15m / 1h | **DAILY-BATCH** (the day's bars after the close) | Cron 16:05 close. 1m 3,687,546 bars, 2026-09-23 → 09-28. 15m 246,767 and 1h 69,930, 09-24 → 09-28. Last run 09-28 23:36. **Not updated during the session** |
| Intraday history (depth: 1m 6 months, 15m/1h since 2022) | **DEFERRED** | decision BACKFILL-DEFER; 293,322 requests planned; 0 run |
| 5m | out of scope (decision D2-5m) | 12 test bars only |
| **Live quotes (LTP, depth), all day** | **NOT IMPLEMENTED** (in production) | `tick_archive` **0 rows**; decision D5 (Stage 7). Audited separately: `docs/LIVE_LTP_DEPTH_AUDIT.md` |
| NSE pre-open (IEP, IIQ, buy/sell quantity, imbalance, depth) | **SNAPSHOT** | Cron 08:25: WebSocket capture 08:55–09:20, then a replay commit (09:20–09:33 measured). `preopen_tick` 1,557,588 rows, 2026-09-24 → 09-29. The data arrives live but reaches the database only after the window |
| Corporate actions | **DAILY-BATCH** (weekly full sweep; new listings daily) | Cron Sat 10:00, plus refresh 06:30. 2,323 events. Last run 09-29 06:30 |
| News & media (Upstox) | **LIVE-INTRADAY** (every 30 minutes, 09:30–15:30) | Cron `30 9` and `0,30 10-15` Mon–Fri. 4,263 runs in 7 days. Last 15:01 today. 230 articles |
| News & media (multi-source: NSE, ET, BS, …) | **NOT IN THE DATABASE**: DRY_RUN files only | `news_item` 0 rows; production writes locked. A separate track |
| Fundamentals | **DAILY-BATCH** (monthly sweep; new listings daily) | 41,805 snapshots; last 09-29 06:30 |
| NIFTY 50, BANKNIFTY, India VIX | **DAILY-BATCH** (1D, with the 07:00 job) | index bars through 09-28 |
| Global markets (S&P, DOW, …), currency, crude | **DAILY-BATCH** | Cron 12:40 and 21:10 daily. 22,032 bars, last label 09-28 |
| Bond yields | **NOT IMPLEMENTED** | no Upstox instrument (vendor unavailable) |
| FII/DII flows | **DAILY-BATCH** | Cron 07:00. 4,920 observations, 2026-04-01 → 09-28; 09-28 knowable 09-29 08:32 IST |
| Instrument master (symbol, ISIN, key, sector, listing status) | **DAILY-BATCH** | Cron 06:30. Sector from fundamentals (profile); lifecycle from the daily master |
| Live feeds (WebSocket) | **SNAPSHOT only** (the pre-open window) | used by the 08:25 pre-open job only; no all-day consumer (see Live quotes) |

## Stage 1: ingestion & storage

| Diagram item | Status | Evidence |
|---|---|---|
| API connectors | Upstox REST + WebSocket: **running**. NSE / news vendors: **DRY_RUN only** | runs above; `news_item` 0 |
| Data validation | **implemented, runs every ingestion** | `ingest_anomaly`, quarantine (Stage 1 criteria J and U PASS) |
| Timestamp normalization | **implemented** | Stage 1 C and X PASS |
| NSE-only filtering | **implemented** | Stage 2 F PASS |
| Data enrichment | **implemented** (instrument mapping, point-in-time sector) | Stage 2 G and H PASS |
| Store in central DB | PostgreSQL: **yes**. Redis cache: **NOT IMPLEMENTED** | no redis package or code |
| Point-in-time rule | **implemented**. F-GLOBAL-FINALITY (global-label finality not evaluated as of the snapshot) was found 2026-09-29 and **fixed in `c6e58b8`** | the recompute of both 29 Sep snapshots now matches all 374,648 stored rows |
| Scheduler (diagram: Celery) | **cron** (not Celery) | 19 active crontab lines; no celery package |

## Stage 2: canonical layer

| Item | Category | Evidence |
|---|---|---|
| Canonical views (bars, news, fundamentals, corporate actions, macro, pre-open, global) | **views over Stage 1 tables**: as current as Stage 1 | `canon_*` views |
| Derived tables (`canon_instrument`, coverage) | **DAILY-BATCH** | Cron 06:40 and 09:10. 19 runs in 7 days; last 09:10 today |
| Stage 2 gate | **PASS** (terminal status); refreshed daily 05:30 from 2026-09-30 | the gate at 14:36 today |

## Stage 3: feature engineering

| Item | Category | Evidence |
|---|---|---|
| Features (65; diagram items: 19 IMPLEMENTED, 6 PARTIAL, 4 UNSUPPORTED, 2 UNKNOWN) | **SNAPSHOT**: PRE_SESSION (as_of 08:59:59) and PRE_OPEN (as_of 09:08:00), once per trading day | `feature_value` 374,648 rows, **one session (09-29), produced by a manual authorised run**. Cron is installed; the **first scheduled run is 2026-09-30** (pending) |
| Intraday or live features | **NOT IMPLEMENTED** (not in the diagram's Stage 3 scope) | only two snapshots per day exist |
| Multi-source news features (`mnews_*`) | **NOT IMPLEMENTED in Stage 3** (a separate track; FEATURE-NEWS-V2 PENDING) | 0 rows |

## Stages 4–8 (models / prediction, signals, risk, execution, monitoring)

| Stage | Category | Evidence |
|---|---|---|
| 4 Models / prediction | **NOT IMPLEMENTED** | no package in `backend/app` (acceptance, api, canon, cli, connectors, contracts, core, db, features, ingest, news, ops, parsers, readapi, sources, storage, vendor, web); no model, prediction or backtest code (every keyword hit is a comment saying such logic is absent); no ML package installed |
| 5 Signals | **NOT IMPLEMENTED** | no signal code; no signal table among the 41 tables |
| 6 Risk | **NOT IMPLEMENTED** | no risk or position code or table |
| 7 Execution (orders, broker) | **NOT IMPLEMENTED** | no order or broker code or table; `app/core/config.py` states nothing reaches orders or brokers |
| 8 Monitoring | **PARTIAL (operations only)** | `prajna ops status` (daily status snapshot 23:55), timing monitor, runbook markers. There is no strategy or P&L monitoring and no alerting |

## Summary

| Category | Items |
|---|---|
| **LIVE-INTRADAY** | Upstox news polling only (every 30 min) |
| **SNAPSHOT** | NSE pre-open (daily window); Stage 3 PRE_SESSION / PRE_OPEN |
| **DAILY-BATCH** | 1D, intraday of the day (after the close), FII/DII, corporate actions, fundamentals, instrument master, global markets, Stage 2 derived tables |
| **HISTORICAL** | 1D from 2020 |
| **DEFERRED** | intraday history depth; Stage 3 feature backfill |
| **NOT IMPLEMENTED** | all-day live LTP/depth persistence; bond yields; Redis; multi-source news in the database; Stages 4–7; strategy monitoring |
