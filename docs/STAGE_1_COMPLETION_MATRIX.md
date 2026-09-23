# Stage 1 completion matrix

**As of 2026-09-23, commit `13ddb9c`, 254 tests passing.**

Every Stage-1 requirement from the strategy diagram ("Data Sources — what we
collect"), one section per item. Where the repository does not establish a
fact, the entry says **UNKNOWN** and names the measurement that would settle it.
Nothing here is inferred from V1 or from vendor marketing.

**Status legend**
- **DONE**: implemented, tested, and validated against the live vendor.
- **BUILT**: implemented and tested, but not yet validated on real market data.
- **SCHEMA**: the table and contract exist; no ingestion yet.
- **NOT STARTED**
- **OUT?**: the source is not approved; a scope decision is needed.

## Summary

| # | Item | Status | Blocking |
|---|---|---|---|
| 1a | Daily OHLCV | SCHEMA | M4 not built; B1 |
| 1b | Intraday OHLCV | SCHEMA | M4 not built; B2 |
| 1c | Live quotes (all-day) | SCHEMA (tick_archive, writer disabled by design) | scope: Stage 7 per M0 |
| 1d | Depth | BUILT for pre-open (full_d5, verified live); d30 unavailable (B3) | — |
| 1e | Historical data | SCHEMA | M4 |
| 2 | NSE pre-open (IEP, IIQ, qty, depth, status) | BUILT; transport validated live, pre-open content NOT yet observed | real pre-open day (B7, B8) |
| 3 | Corporate actions | SCHEMA | Upstox source UNKNOWN |
| 4 | News / media | SCHEMA | Upstox source UNKNOWN; no approved vendor |
| 5 | Fundamentals | SCHEMA | Upstox source UNKNOWN; no approved vendor |
| 6a | NIFTY / BANKNIFTY / India VIX | NOT STARTED (keys exist in master: 139 NSE_INDEX rows) | M4/M6 |
| 6b | FII/DII flows | NOT STARTED | B4 (Upstox capability UNKNOWN) |
| 6c | Global markets, currency, yields | OUT? | no approved source |
| 7 | Instrument master | DONE for universe selection; SCD2 `instrument` table not populated (M3) | M3 |
| 8 | Live WebSocket feeds | BUILT (pre-open recorder, 2 connections); validated live in normal session | real pre-open day |
| — | Session calendar (M2) | DONE (live, 100 days committed) | — |

**Stage 1 is not complete.** Items 1, 3, 4, 5 and 6 have no ingestion. The
pre-open path still lacks its real-day validation. See
`STAGE_1_FINAL_ACCEPTANCE.md` for the decision and what it would take.

---

## 1. Market data

### 1a. Daily OHLCV — SCHEMA
| Field | Value |
|---|---|
| Source | Upstox (only approved vendor) |
| API | `GET /v3/historical-candle/{key}/days/1/{to}/{from}`. The path shape is in `contracts/timeframe.py`, "verified against V1's proven caller"; **not yet called by Prajna** |
| Raw format | JSON: candles as `[ts, o, h, l, c, v, oi]` (per V1). **UNKNOWN in Prajna**; measure by one archived call |
| Archive | would be `PayloadStore` → `var/archive/UPSTOX_REST_V3/…` |
| Parser | none |
| DB destination | `ohlcv_bar` (PK instrument_id, timeframe, session_date, bar_start_utc, source) |
| Provenance | ProvenanceMixin: source, run_id, payload_sha256, fetched_at, knowable_at, knowable_at_verified, knowable_at_basis |
| knowable_at | `knowable.for_daily_bar`: max(session close, fetched_at), **unverified (B1)** |
| Duplicate rule | PK includes source; identical re-ingest = no-op (to be implemented) |
| Conflict rule | two sources may disagree (source is in the PK); a same-source revision is **UNDEFINED**. Needs a decision: B1 asks whether Upstox revises bars after settlement |
| Completeness | `check_coverage` against the trailing baseline (exists, unused) |
| Failure/retry | runner lifecycle exists; per-call retry not built |
| Tests | contract tests only (`test_knowable.py`, `test_identity_and_timeframe.py`) |
| Real validation | none |
| Blocker | M4 not built; B1 (finalisation time); `session_date` must come from `trading_session`, never derived |

### 1b. Intraday OHLCV — SCHEMA
Same as 1a, except:
- **API:** `/{unit}/{step}` (`UPSTOX_INTERVAL` map).
- **knowable_at:** `for_intraday_bar` = max(bar_end, fetched_at), unverified (**B2**).
- **Blocker:** M4. B2 needs a publication-lag measurement: fetch the just-closed bar repeatedly and record when it first appears and when it stops changing.

### 1c. Live quotes (all-day) — SCHEMA, deliberately dormant
- **Source:** the WS v3 feed, the same recorder.
- **Destination:** `tick_archive`, with its writer disabled by `PRAJNA_TICK_PERSISTENCE_ENABLED=false`. M0 scoped it to Stage 7.
- **Today:** the recorder can already archive any window (`--until`), but the only replay path writes `preopen_tick`.
- **Scope decision required:** is all-day tick capture part of Stage 1? If it is, the options are replay into `tick_archive`, or `preopen_tick` extended beyond the pre-open window.

### 1d. Depth — BUILT (pre-open)
- **Feed:** WS v3 `MarketFullFeed.marketLevel.bidAskQuote[]`.
- **Destination:** `preopen_book`, bid and ask paired per rung, with `CHECK` rung 0..29.
- **Verified live 2026-09-23:** mode `full` → `full_d5`, 5 rungs on all 19,474 ticks.
- **`full_d30`:** silently ignored for this account (B3, inferred "no Plus"). 30 rungs are **unavailable**; 5 is the ceiling.

### 1e. Historical data — SCHEMA
Same endpoint family as 1a/1b. There is no backfill tool yet. The depth of history Upstox provides per interval is **UNKNOWN**; measure by requesting progressively older ranges and archiving each response.

---

## 2. NSE pre-open — BUILT; pre-open content not yet observed live

| Field | Value |
|---|---|
| Source | Upstox Market Data Feed **V3** WebSocket (REST quotes carry none of these fields: verified 2026-09-22) |
| Feed | `authorize` `GET /v3/feed/market-data-feed/authorize` → a single-use `wss://wsfeeder-api.upstox.com/market-data-feeder/v3/upstox-developer-api/feeds?...`; subscribe `{"method":"sub","data":{"mode":"full","instrumentKeys":[…≤500]}}` as a binary frame |
| Raw format | protobuf `FeedResponse`; proto vendored with sha256 `3e1c939d…` pinned |
| Archive | `storage/frame_archive.py`: one file per connection, `var/archive/UPSTOX_WS_V3/YYYY/MM/DD/preopen_<day>_<t>Z_c<i>of<n>.frames.gz`, plus `.manifest.json`, plus the session manifest `<stem>.session.json`. Bytes are verbatim, with a sha256 per record, before any decode |
| Parser | `parsers/upstox_feed_v3.py` (pure) |
| DB destination | `preopen_tick` (iep, ieq, iiq_total, iiq_m, rp, tbq, tsq, cas_eligible, atp, vtt, oi, iv, LTPC incl. `ltpc_iep`), `preopen_book`, `preopen_session_status`; `raw_payload` holds one row per frame (`storage_uri = <archive>#seq=N`) |
| Provenance | full mixin on tick and status rows. Book rows inherit from their tick (FK) |
| knowable_at | tick = `FeedResponse.currentTs`, status = `StatusInfo.updatedTime`, both `verified=True`. Bounded by fetched_at on clock skew (WARN `CLOCK_SKEW`). **See PIT finding P1 below** |
| Duplicate rule | unique `(session_date, instrument_key, vendor_ts, source)`. Identical content = "already present" (replay twice, vendor resend) |
| Conflict rule | same key, different content → `DUPLICATE_KEY` **FAIL**; the run rolls back |
| Completeness | per connection: `never_seen` keys → `COVERAGE_DROP`; capacity exclusions → `COVERAGE_CAP`; session manifest union coverage; acceptance check C6 (in-window ticks / subscribed) |
| Failure/retry | per connection: exponential backoff, fresh authorize, resubscribe, bounded (10). The data watchdog keys on subscribed data (fixes the silent-ignore loop found live). Auth failure is never retried. One connection failing never stops the others |
| Tests | `tests/parsers/test_upstox_feed_v3.py`, `tests/storage/test_frame_archive.py`, `tests/sources/test_upstox_preopen_ws.py`, `tests/sources/test_upstox_preopen_session.py`, `tests/integration/test_preopen_replay.py`, `…_capture_end_to_end.py`, `…_failure_recovery.py`, `…_preopen_acceptance.py` |
| Real validation | 2026-09-23 **normal session**, 13:35–13:42 IST: transport, auth, 2 connections × (2,000 + 1,525), mode, depth, latency 11–148 ms, 0 parse issues. **No pre-open data yet**: IEP/IEQ/IIQ/RP were 0 outside pre-open, as expected |
| Blocker | **B7** (iiqM meaning), **B8** (who populates IEP/IIQ). Both need `ops/runbooks/preopen_day.sh` on a trading day. Pre-open boundaries: Upstox does not publish them; the calendar derives 09:00–09:15 for NORMAL sessions and marks it so; the vendor's `preOpenSessionStatus` transitions verify it |

Per field: IEP (`iep`, and `ltpc_iep` with real presence), IIQ (`iiq_total`,
`iiq_m`), indicative buy/sell (`tbq`/`tsq`), equilibrium quantity (`ieq`),
depth (`preopen_book`) and status transitions (`preopen_session_status`, the
vendor string kept verbatim, including `PRE_OPEN_M_END`) all share the row
above. proto3 cannot distinguish `iep = 0` from "not sent" (B8).

---

## 3. Corporate actions — SCHEMA
| Field | Value |
|---|---|
| Source | Upstox, per constraint. **UNKNOWN whether Upstox exposes corporate actions.** The `corporate_action` model docstring says "Upstox's authoritative corporate-actions feed", but no endpoint is named or called anywhere in the repo |
| Measurement | check Upstox API docs and probe candidates with the live token; archive the responses. If no such API exists: **STOP and report**. Do not substitute NSE (constraint 5) |
| DB destination | `corporate_action` (ISIN-keyed, 9 action types, ex_date / record_date / announced_at) |
| knowable_at | `for_announced_fact(announced_at, fetched_at)`: verified only if the vendor gives an announcement time; **never** ex_date |
| Duplicate/conflict | `uq_ca_observation (isin, action_type, ex_date, vendor_action_id, source)`. Revisions are UNDEFINED |
| Status | no source, parser, ingest or tests beyond the schema |

## 4. News / media — SCHEMA
- **Source: UNKNOWN.** Upstox is not established as a news provider. The diagram's "ET, BS, etc." are **not approved vendors**.
- **Destination:** `news_article`. It has no ticker column by design; entity resolution happens later, in Stage 2/3.
- **knowable_at:** `for_announced_fact(published_at, fetched_at)`.
- **Scope decision required:** approve a news vendor, or remove news from Stage 1.

## 5. Fundamentals — SCHEMA
- **Source: UNKNOWN.** No Upstox fundamentals endpoint is established.
- **Destination:** `fundamental_snapshot`: append-only, with knowable_at in the key.
- **knowable_at:** the vendor's report time if it supplies one; else fetched_at (unverified). Never `period_end`.
- **Scope decision required.**

## 6. Market / macro data
- **NIFTY / BANKNIFTY / India VIX: NOT STARTED.**
  - Keys exist in the archived master: 139 `NSE_INDEX` rows. The Phase-0 doc names `NSE_INDEX|India VIX`.
  - Possible paths: the WS `indexFF` (the parser already maps its LTPC into a tick row), or historical candles (M4).
  - Destination: `macro_observation`, or `ohlcv_bar` for index bars; to be decided.
  - knowable_at: as for bars (B1/B2).
- **FII/DII flows: NOT STARTED, B4.** Upstox capability is UNKNOWN. The constraint is explicit: if Upstox lacks it, STOP; no NSE crawler.
- **Global markets (S&P, DOW), currency, yields: OUT?** No approved source.
  - Upstox's master has `NSE_COM`, `NCD_FO` and `MCX`-type segments (currency and commodity *derivatives*). These are not the spot series the diagram implies.
  - **Scope decision required.**

## 7. Instrument master — DONE (selection); M3 persistence pending
| Field | Value |
|---|---|
| Source | `https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz`, public, no token |
| Raw format | gzipped JSON array. Fields (live, 2026-09-23): exchange, exchange_token, freeze_quantity, instrument_key, instrument_type, isin, lot_size, name, qty_multiplier, security_type, segment, tick_size, trading_symbol. **No sector and no listing-status field**, which the diagram lists; Upstox does not supply them in this file |
| Archive | `PayloadStore` → `var/archive/UPSTOX_ASSETS/…/<sha>.json.gz.gz`, stored as served (still gzipped) |
| Parser | `parsers/upstox_instrument_master.py` (pure; every row accounted for) |
| DB destination | `instrument_universe_membership` (universe `preopen` + `preopen.cap_excluded`). **The `instrument` SCD2 table is not populated (M3)** |
| Provenance | full mixin; payload_sha256 = the master file; the run records `rules_sha256`, cap and `cap_verified=false` |
| knowable_at | `for_snapshot_download`: fetched_at, unverified (the file carries no publication time) |
| Duplicate rule | identical re-selection for the same session is a no-op; the dedup is content-addressed |
| Conflict rule | a different selection for a recorded session → `DUPLICATE_KEY` FAIL; never merged |
| Completeness | named-rule accounting (sum of counts = rows); coverage vs the last universe (<80% → FAIL) |
| Failure/retry | a download HTTP error is loud; no retry |
| Tests | `tests/contracts/test_universe.py`, `tests/parsers/test_upstox_instrument_master.py`, `tests/sources/test_upstox_instruments.py`, `tests/integration/test_universe_selection.py` |
| Real validation | 2026-09-23: 80,226 rows, sha `bf4a5db8…`, **3,525 eligible** (INE 3,172 / INF 351 / IN9 2). Dry run only |
| Open policy | REIT series `RR` (6) excluded while InvIT `IV` is included; D1/E1/IT/SZ/W1 excluded. **User decision pending** |

## 8. Live WebSocket feeds — BUILT
See §2 for the pre-open use. The same client, with 2 connections and 2,000
keys each (measured), can record any window. All-day persistence is §1c.
Known network risk: intermittent TLS hostname mismatches and resets on the
local network (see `2026-09-23_M1_LIVE_SMOKE.md`). Verification is never
relaxed.

## Session calendar (M2) — DONE
| Field | Value |
|---|---|
| Source | Upstox `GET /v2/market/holidays` (classification) + `GET /v2/market/timings/{date}` (hours), authenticated |
| Raw format | JSON; semantics measured and recorded as `tests/fixtures/upstox_calendar/*` (real bytes) |
| Archive | `var/archive/UPSTOX_REST_V2/…`; holidays payload sha `eff843d4…` |
| Parser | `parsers/upstox_calendar.py` (pure) |
| DB destination | `trading_session` |
| knowable_at | fetched_at, unverified (no publication time) |
| Duplicate/conflict | one row per date: identical → no-op; different → FAIL, row untouched |
| Completeness | every date in range decided or the run fails; contradictions between the two endpoints fail |
| Real validation | 2026-09-23..2026-12-31 committed: 67 NORMAL, 27 WEEKEND, 5 HOLIDAY, 1 SPECIAL (Muhurat 18:00–19:00), 0 anomalies. B9 resolved: SETTLEMENT_HOLIDAY ≠ closed |
| Limits | pre-open window only for NORMAL/09:15 sessions (derived); special sessions have none (UNKNOWN). The holiday list covers 2026; 2027 needs a fresh fetch once Upstox publishes it |

---

## Point-in-time audit

The question for each source: *could this value have been known at the
timestamp at which a strategy would consume it?*

| Source | knowable_at rule | Verdict |
|---|---|---|
| Pre-open tick | vendor `currentTs` (verified), bounded by fetched_at | **P1: overclaims by the transport latency** (below) |
| Pre-open status | vendor `updatedTime` (verified), bounded by fetched_at | P1 applies |
| Instrument master / universe | fetched_at (unverified) | safe: can only be late |
| Session calendar | fetched_at (unverified) | safe |
| Daily / intraday bars | max(close or bar_end, fetched_at), unverified | safe by construction; unmeasured (B1/B2) |
| Corporate actions / fundamentals / news | announcement or publication time if the vendor gives one, else fetched_at | safe by construction; no data yet |

**Read-side guard:** `knowable.assert_knowable_before` is strict `<`. Every
table carries `CHECK knowable_at <= fetched_at`, enforced by the DB (tested).

**P1 (finding, needs a decision).** For WebSocket rows, knowable_at is the
vendor's emission time. We receive the frame 11–148 ms later (median ~16 ms,
measured 2026-09-23). To any subscriber the fact exists at `currentTs`, but
*this system* could not act on it before `fetched_at`. A backtest that
consumes `preopen_tick` by `knowable_at` can therefore act up to ~150 ms before
the frame was actually held.
- **Materiality:** negligible for a strategy deciding at 09:15 from the
  09:00–09:08 auction. It is still an overclaim, and constraint 10 forbids that.
- **Options:**
  - (a) set knowable_at = fetched_at for WS rows, keeping vendor time in `vendor_ts`;
  - (b) keep it and require consumers to use fetched_at.
- **Status:** not changed here, because it alters the M0 contract (`for_preopen_tick`). **User decision.**

## Failure / recovery test index

| Case | Test |
|---|---|
| Duplicate frame | `test_failure_recovery::test_identical_frame_twice_in_one_archive_is_one_observation` |
| Conflicting observation | `test_preopen_replay::test_conflicting_observation_fails_instead_of_keeping_the_first` |
| Dropped connection | `test_upstox_preopen_ws::test_drop_reauthorizes_and_resubscribes`, `test_upstox_preopen_session::test_drop_and_stale_are_per_connection` |
| Stale feed | `test_upstox_preopen_ws::test_stale_feed_is_detected_and_recycled`, `…::test_silently_ignored_subscription_still_gives_up` |
| Token expiry | `test_upstox_preopen_ws::test_auth_failure_is_not_retried`, `…::TestFeedAuthorize::test_expired_token_is_auth_error`, `test_failure_recovery::test_capture_refuses_an_expired_token_before_opening_anything` |
| Partial archive / crash | `test_frame_archive::test_a_crash_keeps_every_completed_record`, `test_preopen_replay::test_crashed_capture_replays_what_it_has_and_says_so` |
| Archive tampering | `test_frame_archive::test_corrupted_payload_is_detected_not_decoded`, `test_preopen_replay::test_tampered_archive_is_rejected`, `test_preopen_capture_end_to_end::…forged manifest` |
| Malformed protobuf | `test_upstox_feed_v3::test_undecodable_bytes_raise`, `test_preopen_replay::test_undecodable_frame_fails_the_run_but_stays_archived` |
| Unknown field / schema drift | `test_upstox_feed_v3::test_unknown_field_is_schema_drift`, `…::test_unknown_request_mode_is_drift_and_named`, `test_failure_recovery::test_schema_drift_in_a_live_frame_fails_the_replay` |
| Missing instrument | `test_upstox_preopen_ws::test_keys_that_never_produce_a_frame_are_named`, `test_failure_recovery::test_never_seen_key_becomes_a_database_anomaly` |
| Subscription-cap exclusion | `test_universe::TestCap`, `test_upstox_preopen_session::test_capacity_exclusions_are_recorded_once`, `test_preopen_capture_end_to_end::test_capture_then_replay` |
| Incomplete universe | `test_universe_selection::test_universe_collapse_against_the_last_session_fails`, `test_upstox_preopen_session::test_one_connection_failing_does_not_stop_the_others` |
| Replay twice | `test_preopen_replay::test_replay_twice_is_idempotent`, session variant in `test_preopen_capture_end_to_end` |
| Replay after interrupted run | `test_failure_recovery::test_replay_after_an_interrupted_replay` |
| DB transaction rollback | same test (all staged rows gone, run FAILED, rows_written 0); `test_calendar_ingest::test_one_contradiction_fails_the_whole_run` |
