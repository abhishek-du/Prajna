# Stage 2: Data Processing & Storage (design)

**Status:** development started on 2026-09-24, while Stage 1 backfills still
run. The Stage 1 acceptance gate is unchanged, and Stage 3 and later stay
locked.

## 0. What Stage 1 already provides (reused, not duplicated)

| Concern | Stage 1 implementation, reused as-is |
|---|---|
| Vendor access, auth, retry, backoff, 429 stop, rate limit, 60 s wall timeout | `vendor/upstox/rest.py` (UpstoxRestClient, RateLimiter) |
| Raw, immutable, content-addressed archive | `storage/payload_store.py`, `storage/frame_archive.py`, `raw_payload` |
| Run ledger, anomalies, checkpoints | `ingest/runner.py` (IngestRunner), `ingest_run`, `ingest_anomaly`, `ingest_watermark` |
| OHLCV validation, Q1 quarantine | `contracts/timeframe.validate_bar`, `parsers/upstox_candles.py`, DB CHECK `ck_ohlcv_sane` |
| Timestamp contracts | `contracts/knowable.py` (for_daily_bar, for_intraday_bar, for_preopen_tick P1, for_announcement_date KN-CA, for_announced_fact), `contracts/candles.py` (D4 daily key, completion margin, global D+1 12:00 rule) |
| Read-side look-ahead guard | `contracts/knowable.assert_knowable_before` (strict `<`) |
| Trading calendar | `trading_session`, 2020-01-01 to 2026-12-31, cross-checked with NIFTY 50 |

The Stage 2 prompt mentions a "03:45 UTC / 09:15 IST daily convention".
Prajna's recorded contract is **D4**:
- a daily bar is keyed by `session_date`, with `bar_start_utc` = 00:00 IST,
  kept as a label;
- it becomes knowable only after the session: `max(close, fetched_at)`;
- a 09:15 timestamp for a daily bar was V1's look-ahead defect (status report
  §9).

Stage 2 keeps D4 and invents no new contract. Its API exposes
`event_start` / `event_end` for a bar explicitly:
- for daily bars, the session's open and close times from `trading_session`;
- for intraday bars, `bar_start` and `bar_start + width`.

## 1. Components

| Stage 2 component | Module | Notes |
|---|---|---|
| 2.1 API connectors | `app/connectors/` | a `Connector` protocol with a classifying fetch over the existing Upstox client (§2). Upstox only (constraint #1): NSE data reaches Prajna through Upstox, so there is no NSE crawler |
| 2.2 Validation | `app/canon/validate.py` | the same rules as ingest (reused) plus DB audits for canonical inputs |
| 2.3 Timestamps | `app/canon/time.py` | the one place Stage 3+ gets event_start/end, market_date, knowable_at, fetched_at |
| 2.4 NSE filter | `app/canon/universe.py` → table `canon_instrument` | a deterministic rule set with a versioned hash; every instrument gets a decision and a reason |
| 2.5 Enrichment | `canon_instrument` (sector, universe membership) plus views | no indicators (those are Stage 3) |
| 2.6 Central storage | migration `0005_canon` | tables `canon_instrument`, `canon_coverage`; views `canon_market_bar`, `canon_corporate_action`, `canon_news`, `canon_fundamental`, `canon_preopen`, `canon_macro` |
| PIT read API (Stage 3 contract) | `app/canon/pit.py` | every read takes `as_of` and returns only rows with `knowable_at < as_of` |
| Processing (incremental, idempotent) | `app/canon/process.py`, CLI `prajna stage2 process` | run ledger with source `PRAJNA_CANON`; checkpoint in `ingest_watermark` |
| Quality gates | `app/canon/quality.py`, CLI `prajna stage2 quality` | |
| Acceptance | `app/acceptance/stage2.py`, CLI `prajna acceptance stage2` → `docs/STAGE_2_ACCEPTANCE.md` | criteria A–P |

## 2. Error classification (connectors)

Each outcome is a `FetchOutcome`:
- `OK_DATA`
- `OK_EMPTY_WINDOW`: valid and empty; the vendor said there was nothing
- `EMPTY_BODY`
- `MALFORMED`: not JSON / wrong envelope
- `STRUCTURALLY_INVALID`: JSON, but the shape breaks the contract
- `HTTP_ERROR`
- `VENDOR_ERROR`: 4xx with a vendor code
- `AUTH_ERROR`
- `RATE_LIMITED`
- `TIMEOUT`
- `TRANSPORT_ERROR`

No error becomes "empty data". Each result also carries:
- `fetched_at`
- `source`
- endpoint and URL
- HTTP status
- request id (from the vendor response header, when present)
- retry count and attempts
- raw bytes

## 3. Data-availability states (`canon_coverage`)

There is one row per (NSE instrument, timeframe in scope, trading session
within the approved depth). Each row carries exactly one state:

| State | Meaning |
|---|---|
| `DATA` | at least one stored bar that session. `bars` and `quarantined` are counted |
| `QUARANTINED` | no stored bar, but the vendor's bar(s) for the session were quarantined (Q1) |
| `EMPTY` | a successful ingest window covered the session and the vendor returned no bar (no trades, or not listed yet) |
| `VENDOR_ERROR` | the latest ingest of a window covering the session failed with a vendor error |
| `PENDING_BACKFILL` | inside the approved depth, but no stream checkpoint covers it yet (Stage 1 still running) |
| `MISSING` | inside the covered range, yet no successful window covers it. This is an inconsistency, and a quality gate fails on it |
| `OUT_OF_SCOPE` | recorded rather than stored: timeframe 5m (D2-5m), and dates before the approved depth |

Nothing is ever filled in: no zero, no forward fill, no interpolation.

## 4. Point-in-time rule

Every PIT read requires `as_of` and applies `knowable_at < as_of`, the same
strictness as `assert_knowable_before`. Each returned row is re-checked in
Python as well (defence in depth). Per source:
- **Bars:** `knowable_at` from Stage 1.
  - Daily: `max(close, fetched_at)` (B1).
  - Intraday: `max(bar_end, fetched_at)` (B2).
- **Corporate actions:** KN-CA.
- **News:** `published_time`, verified.
- **Fundamentals:** `fetched_at`. The latest snapshot per statement type is
  taken among those knowable before `as_of`.
- **Pre-open:** vendor `currentTs` (P1).
- **FII/DII:** `fetched_at`.

## 5. Idempotency and increments

- **Checkpoint:** the stream `canon.process` in `ingest_watermark` (source
  `PRAJNA_CANON`) stores the `finished_at` of the last Stage 1 run it
  consumed.
- **What a run recomputes:** only the (instrument, timeframe) pairs touched
  by Stage 1 runs finished after the checkpoint, plus the whole universe when
  the instrument table changed.
- **Upserts:** a row is written only when its content differs, so an
  identical rerun writes 0 rows.
- **Crash safety:** a crash rolls the run back, and the checkpoint only
  advances in the same transaction as the rows.

## 6. Safety

- `STAGE2_LIVE_ENABLED` (default false) gates any future live, continuous
  mode. Stage 2 has no order, signal or broker path.
- Stage 2 makes **no Upstox calls** during processing, so it cannot disturb
  Stage 1's quota.
