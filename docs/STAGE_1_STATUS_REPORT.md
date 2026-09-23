# Prajna: Stage 1 status report

**Date:** 2026-09-23 (IST), 18:50
**Code:** commit `d72df15` (19 commits, M0 through M4.3)
**Tests:** **438 passed, 0 failed**
**Database:** `prajna` (Docker `postgres:18`, loopback-only)

Evidence in more detail:
- [`STAGE_1_COMPLETION_MATRIX.md`](STAGE_1_COMPLETION_MATRIX.md): the per-source audit
- [`STAGE_1_FINAL_ACCEPTANCE.md`](STAGE_1_FINAL_ACCEPTANCE.md): criteria A–N
- [`2026-09-23_M1_LIVE_SMOKE.md`](2026-09-23_M1_LIVE_SMOKE.md): the first live WebSocket test

---

## 1. Short answer

### Stage 1 is **NOT COMPLETE**.

What is solid today:
- The **foundation is complete and tested**: isolation, provenance, raw archive,
  point-in-time rules, replay, and fail-closed behaviour.
- **Live, in the database:**
  - the trading calendar: **100 days**;
  - the instrument master: **3,528 instruments**.
- **Built and tested, not yet run live into the database:**
  - the pre-open WebSocket recorder;
  - candle ingestion (1D, 1m, 5m, 15m, 1h).

**Market data (candles, LTP, depth, pre-open) is not in the database yet.**
`ohlcv_bar` = 0 and `preopen_tick` = 0.

What remains, in three parts:
1. A **real pre-open day** (09:00–09:15 IST): this is what resolves B7 and B8.
2. **The first real commit of candles**, and the daily job.
3. **Scope decisions:** corporate actions, fundamentals, news and FII/DII. For
   most of these it is not yet known whether Upstox provides them at all.

---

## 2. Stage 1 of the diagram, item by item

Legend:
- ✅ done, live data in the DB
- 🟢 built and tested, not yet run live into the DB
- 🟡 partly done
- 🔴 not started
- ⚪ not an approved source / scope decision needed

### Column 1: Data sources (what we collect)

| Item in the diagram | Status | Where it stands |
|---|---|---|
| **Market data, daily (1D)** | 🟢 | ingestion built (M4.3); live dry-run returned 10 bars for each of 3 instruments; history from 2000 is available; **0 rows in the DB** |
| **Market data, intraday 1m / 5m / 15m / 1h** | 🟢 | ingestion built; live dry-run returned 375 complete 1m bars for each of 3 instruments; history from 2022-01; **0 rows in the DB** |
| **Live quotes (LTP, depth)** | 🟡 | WebSocket recorder built and live-tested (2 × 2,000 keys, 5-level depth). All-day tick storage (`tick_archive`) is **Stage 7 per the M0 decision** (D5) |
| **Historical data** | 🟢 | windows planned by measured limits (1m: month, 1h: quarter, 1D: decade); no backfill yet (D1) |
| **NSE pre-open: IEP / IIQ / buy-sell qty / imbalance** | 🟢 | recorder, archive, parser, replay and acceptance harness all built; **no real pre-open day yet** (B7/B8) |
| **Corporate actions** | ⚪ | schema only; **UNKNOWN whether Upstox provides an API** |
| **News & media** | ⚪ | schema only; no approved source (ET/BS are not approved vendors) |
| **Fundamentals** | ⚪ | schema only; UNKNOWN whether Upstox provides it |
| **Market & macro: NIFTY 50, BANKNIFTY, India VIX** | 🟡 | all three are in the `instrument` table; candle ingestion works for them (Nifty 50 dry-run OK); **0 rows** |
| **Global markets (S&P, DOW), currency, yields** | ⚪ | Upstox has no approved source; scope decision needed |
| **FII/DII flows** | ⚪ | blocker B4: Upstox capability UNKNOWN; substituting NSE is not allowed |
| **Instrument master** (symbol, ISIN, key) | ✅ | 3,528 current instruments in the DB. **Sector and listing status are not in the Upstox master** |
| **Live feeds (WebSocket)** | 🟢 | tested live; per-connection cap measured; all 3,525 instruments covered by 2 connections |

### Column 2: Ingestion & storage

| Item in the diagram | Status | In Prajna |
|---|---|---|
| **1. API connectors** | 🟡 | Upstox REST (rate limited) and WebSocket built. NSE and News connectors are **not approved** (Upstox-only rule) |
| **2. Data validation** | ✅ | schema drift, OHLC sanity, precision, windows, duplicate/conflict, coverage; every issue becomes an `ingest_anomaly` |
| **3. Timestamp normalization** | ✅ | stored `session_date`, tz-aware UTC, IST rules, holidays and weekends from the calendar. **Differs from the diagram**, see §9 |
| **4. NSE-only filtering** | ✅ | `segment == NSE_EQ` rule; BSE and others excluded under named rules |
| **5. Data enrichment** | 🟡 | instrument mapping done (`instrument_id` FK). Sector tags are not available from Upstox; events not started |
| **6. Store in central DB** | ✅ / 🔴 | PostgreSQL done; Redis is not used (not needed in Stage 1) |
| **Key rule: point-in-time, no look-ahead** | ✅ | `knowable_at <= fetched_at` enforced by the DB on every table; strict `<` read guard; finding P1 open (§8) |

---

## 3. What data we have now (`prajna` database)

| Table | Rows | What it is |
|---|---|---|
| `trading_session` | **100** | NSE calendar 2026-09-23 → 2026-12-31: 67 NORMAL, 27 WEEKEND, 5 HOLIDAY, 1 SPECIAL (Muhurat 11-08, 18:00–19:00) |
| `instrument` | **3,528** | 3,525 NSE_EQ (EQ 2,670 · SM 467 · BE 237 · ST 103 · BZ 27 · IV 21) + Nifty 50, Nifty Bank, India VIX |
| `raw_payload` | 74 | provenance index of archived vendor responses |
| `ingest_run` | 13 | run ledger (calendar, instruments, universe, candle dry-runs) |
| `ingest_anomaly` | 1 | a COVERAGE_CAP from the old single-connection universe dry-run |
| `ingest_watermark` | 2 | checkpoints |
| `instrument_universe_membership` | 0 | the universe is committed on the morning of capture (runbook) |
| `ohlcv_bar` | **0** | candle ingestion built, but only dry-runs so far |
| `preopen_tick` / `preopen_book` / `preopen_session_status` | **0** | the pre-open day has not happened yet |
| `tick_archive` | 0 | Stage 7 (M0 decision) |
| `corporate_action`, `fundamental_snapshot`, `news_article`, `macro_observation` | 0 | not started |

### Raw archive (`backend/var/archive/`, gitignored)

| Source | Files | Size | What it holds |
|---|---|---|---|
| `UPSTOX_ASSETS` | 1 | 1.9 MB | instrument master 2026-09-23 (sha `bf4a5db8…`, 80,226 rows) |
| `UPSTOX_REST_V2` | 76 | 328 KB | holidays, 100 days of timings, market status, quotes |
| `UPSTOX_REST_V3` | 798 | 3.9 MB | candle probes, the B1/B2 poller, dry-runs |
| `UPSTOX_WS_V3` | 10 | 5.2 MB | 5 WebSocket smoke archives + manifests |

---

## 4. What has been implemented (milestone by milestone)

| Milestone | Commit | What it contains |
|---|---|---|
| **M0 Foundation** | `51709bd` | Separate `prajna` DB and role; V1 isolation guard; contracts (session, identity, timeframe, knowable, provenance); 16-table schema; content-addressed archive; run lifecycle; write token; test isolation (network blocked, test DB only) |
| Tooling | `fc5b5ab`, `c839a9f` | `db sql/tables/describe`, read-only web viewer |
| **Environment rebuild** | `725e294`, `616a717` | After the OS reinstall: git, Docker Postgres 18, Python 3.11 via uv; Upstox token mint/probe |
| **M1 Pre-open pipeline** | `8154e2b` | Upstox V3 proto vendored and pinned; frame archive (verbatim, sha per record, crash-safe); pure parser; idempotent replay |
| **M1 Recorder** | `f09b412` | WebSocket: authorize → connect → subscribe, event-driven readiness, heartbeat, stale watchdog, bounded reconnect |
| **M1 Universe** | `eeac6d1` | Selection from the instrument master (no ISIN rule), sort-then-cap, provenance, reproducible |
| **M1 Live fix** | `0049cda` | Fixed the silent-ignore loop found live; smoke results recorded |
| **M1 Multi-connection** | `58ccdae` | 2 connections × ≤2,000, per-connection archive/reconnect/stale, session manifest, session replay |
| **M2 Calendar** | `8f95cc4` | Upstox holidays + timings, both must agree; NORMAL/SPECIAL/HOLIDAY/WEEKEND; 100 days live |
| **Stage 1 harness** | `13ddb9c` | Pre-open acceptance harness (B7/B8 only from real data); failure/recovery tests |
| Docs | `94f535f` | Completion matrix, final acceptance (NOT COMPLETE), real-day runbook |
| **M3.0 Instruments** | `693f9ab` | 3,528 current instruments from the archived master, never-overwrite rule, acceptance I1–I7 PASS |
| **M4.0 Candle contract** | `7725191` | Request windows, completeness (120 s margin; daily only after the session day), D4 daily key, coverage outcomes |
| **M4.1 REST client** | `a866095` | Rate limiter (90% of 50/s, 500/min, 2000/30min), retry/backoff, 429 = stop |
| **M4.2 Candle parser** | `ab6b8ea` | Pure parser, 13 real responses as fixtures, forming/settling/complete |
| **M4.3 Candle ingest** | `d72df15` | Archive → parse → complete-only → `ohlcv_bar`; resumable checkpoint; conflict = FAIL |

### Command-line tools available now

```
prajna db check-isolation | upgrade | status | tables | describe | sql | web
prajna upstox login | token-status
prajna ingest calendar      --from --to [--commit]
prajna ingest universe      --download | --from-file | --payload-sha256  [--commit]
prajna ingest instruments   --payload-sha256 [--commit]
prajna ingest preopen-capture --universe-date | --keys-file  --until 09:20
prajna ingest preopen       --replay-from-session | --replay-from-archive [--commit]
prajna ingest candles       --timeframe ... (--from/--to | --intraday) (--key | --keys-file | --all-instruments) [--commit]
prajna acceptance preopen   --session <manifest>
prajna acceptance instruments --payload-sha256 <sha>
ops/runbooks/preopen_day.sh [--login] <date>      # the real pre-open day, end to end
```

---

## 5. Testing: what has been proven

**438 tests, all green.** None of them touch the network; they use real
recorded Upstox payloads as fixtures, loopback fake servers, and a separate
`prajna_test` database.

| Area | What is tested |
|---|---|
| Isolation and safety | V1 DB refused, write token, network blocked, no Kite/yfinance |
| Contracts | knowable_at rules, sessions, timeframes, universe, windows, completeness, D4 |
| Archive | byte-exact round trip, crash (truncated tail), tamper detection |
| Parsers | protobuf feed, instrument master, calendar, candles; all on **real payloads** |
| Pre-open | recorder (drop, stale, reconnect, 429, auth), multi-connection, replay, acceptance |
| Calendar | real holidays/timings, contradictions fail, no overwrite |
| Instruments | real 80,226-row master, identical = no-op, change = FAIL, acceptance chain |
| REST client | rate-limiter windows (a 10,000-call run), retry, 429 stop, token never leaked |
| Candle ingest | provenance, idempotence, multi-window, forming bars, conflict, 429 → resume → skip, crash → rollback |

Checks beyond the tests:
- **Mutation checks:** for the most important rules I broke the code on
  purpose and confirmed the tests catch it: the ISIN rule, the completion
  margin, the daily rule, the window check, and three checkpoint rules.
- **Bugs caught by tests, fixed before any commit:**
  - rate-limiter float precision (it admitted 1,801 calls in an 1,800 window);
  - a WebSocket silent-ignore loop;
  - the intraday checkpoint jump;
  - the same-day daily checkpoint skip;
  - the `infinity` date comparison.

---

## 6. What live Upstox has proven

| Question | Answer (measured) |
|---|---|
| B0: token | TOTP login works; tokens expire daily ~03:30 IST |
| B3: 30-level depth | `full_d30` is ignored silently, so the account most likely has no Plus; **5 levels** is the ceiling |
| B5: subscription cap | **2,000 keys per connection**; 2 concurrent connections covered **all 3,525** |
| B6: mode | `full` → `full_d5` |
| B9: holiday list | SETTLEMENT_HOLIDAY does **not** mean NSE is closed; resolved |
| Candle history | 1D from **2000-01-03**; 1m/5m/15m/1h from **2022-01**; per request 1 month / 1 quarter / 1 decade |
| B2 (1 session) | a 1m bar appears 6–36 s after its minute ends; 5m/15m/1h serve forming bars |
| B1 (1 session) | a daily bar is **not published the same day** (not even by 18:45); the intraday daily bar changed until ~16:02 |
| Data consistency | 1m → 5m/15m/1h aggregation 0 mismatches; WS LTP 37/37 inside the 1m range |
| Rate limits | 50/s, 500/min, 2000/30min per API per user (Upstox docs) |

---

## 7. Open blockers and decisions

**Waiting on a measurement:**
- **B7, B8:** a real pre-open day (09:00–09:15).
- **B1, B2:** at least 3 more sessions.
- Behaviour on a 429 response.
- Whether candles exist for delisted instruments.

**Needs your decision:**
- **D1:** history depth. 1D since 2000 is cheap. 1m since 2022 is about
  **1.5 billion rows**, which takes ~50 h to fetch.
- **D2:** 5m/15m/1h fetched from Upstox, or derived from 1m.
- **D3:** candle revisions: FAIL (today's rule), or store each version (needs a migration).
- **D5:** all-day LTP/depth in Stage 1, or in Stage 7.
- **S1:** include REITs (series RR) and D1/E1/IT/SZ/W1, or not.
- **S2:** corporate actions, fundamentals, news, FII/DII: check Upstox first
  (and stop if it doesn't provide them), or remove them from Stage 1.
- **P1:** WebSocket knowable_at is 11–148 ms before our receipt. Change it to
  `fetched_at`? That changes an M0 contract.
- **Survivorship:** the historical universe contains only instruments listed
  today. Accept and document this, or not.

**Operational risks:**
- Intermittent TLS problems on the local network.
- The rate limiter only works within one process.

---

## 8. What is left to complete Stage 1 (in order)

1. **Real pre-open day:** `ops/runbooks/preopen_day.sh --login <date>`,
   started before 08:50 IST. This closes H and L, and resolves B7/B8.
2. **First real candle commit:** a few instruments, 1D + 1m, into the DB.
3. **M4.4:** daily incremental job (1D + 1m after close) for 3,525 + 3 indices.
4. **M4.5:** historical backfill, at the depth D1 sets.
5. **M4.6:** B1/B2 measured over ≥ 3 sessions, then knowable_at `verified`.
6. **M4.7:** a market-data acceptance harness.
7. **S2 scope:** check Upstox endpoints for corporate actions, fundamentals and
   FII/DII; implement them, or remove them from Stage 1 with a written reason.
8. Regenerate `STAGE_1_FINAL_ACCEPTANCE.md`, and declare COMPLETE only when
   criteria A–N are all met.

---

## 9. Where Prajna deliberately differs from the diagram

| Diagram | Prajna | Why |
|---|---|---|
| "API connectors (Upstox, **NSE**, News)" | Upstox only | a non-negotiable constraint; NSE crawlers and unapproved vendors are not allowed |
| "Daily: **03:45 UTC (9:15 IST)** exactly one timestamp" | A daily bar is keyed by `session_date` (IST midnight label, D4); its knowable_at is **after the close, the next day** | at 09:15 the day's bar does not exist yet. Treating it as 09:15 is exactly V1's look-ahead mistake |
| "Instrument master: sector, listing status" | not available | Upstox's master does not have these fields |
| "Store in central DB (Postgres + **Redis cache**)" | Postgres only | Stage 1 does not need a cache; it belongs to a later stage |
| "Global markets, FII/DII" | not approved / B4 | no Upstox source is established |
| "Celery task scheduler" | CLI + runbook | a scheduler is needed from M4.4 onwards; not yet decided |
