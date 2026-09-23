# Stage 1 — final acceptance

**Date:** 2026-09-23 (IST).
**Commits:** code `13ddb9c` plus the docs/runbook commit that adds this file.
**Tests:** 254 passed, 0 failed.

## Decision

# STAGE 1 = NOT COMPLETE

Three independent reasons. Any one of them is sufficient:

1. **L/H — no real pre-open day yet.** The pre-open path has been validated
   live only during a normal session (2026-09-23, 13:35 IST). No archive yet
   contains 09:00–09:15 data, so B7 and B8 are unresolved by rule.
   → Run `backend/ops/runbooks/preopen_day.sh` on 2026-09-24.
2. **A — most diagram sources have no ingestion.** Daily/intraday/historical
   OHLCV, indices and India VIX, corporate actions, fundamentals, news and
   FII/DII exist only as schema or not at all (matrix §1, §3–§6).
3. **N — unknowns are neither resolved nor removed from scope.** Whether Upstox
   provides corporate actions, fundamentals, news or FII/DII is UNKNOWN (B4 and
   matrix §3–§6). Global markets, currency and yields have no approved source.
   Removing any of these from Stage 1 is a scope decision that has not been
   made.

Stage 2 must not start on this record.

---

## Acceptance criteria

| # | Criterion | Status | Evidence / gap |
|---|---|---|---|
| A | Every in-scope source implemented | **FAIL** | Implemented: instrument master (universe), session calendar, pre-open WS. Not implemented: OHLCV (M4), indices/VIX, corporate actions (M5), FII/DII (B4), fundamentals/news (M7). The scope is undecided (N) |
| B | Raw archived before transformation | PASS (implemented sources) | master: `PayloadStore.put` before `parse_master`; calendar: every payload `put` before parse; WS: `append_frame` before any decode. Tests: `test_dry_run_archives_but_writes_no_rows`, `test_undecodable_*_stays_archived` |
| C | Provenance on every persisted row | PASS | `ProvenanceMixin` on all observation tables, with FKs to `ingest_run` and `raw_payload`; `check_provenance_complete` gates writes; book rows inherit via FK |
| D | Documented knowable_at per source | PASS, with finding | every source has a rule (matrix §PIT). **P1:** WS knowable_at overclaims by 11–148 ms; the decision is open |
| E | Duplicate/conflict defined + tested | PASS (implemented sources) | pre-open: identical = no-op, different = FAIL. Universe and calendar: one assertion per session/day, change = FAIL. Bar revisions are UNDEFINED (M4) |
| F | Failure/recovery tested | PASS | 15/15 cases indexed in the matrix, each with ≥1 test |
| G | Universe deterministic + auditable | PASS | sort-then-shard; `rules_sha256`, master sha and members sha persisted; re-selection from the archived payload is identical (tested). Open policy: RR/D1/E1/IT/SZ/W1 series |
| H | B7/B8 from real pre-open data | **FAIL (pending)** | the harness refuses synthetic data (tested); a real day has not happened yet |
| I | Session calendar operational | PASS | 100 days committed live (run `f8e1d2c2`), 0 anomalies; tomorrow = NORMAL 09:15–15:30, pre-open 09:00–09:15 (derived) |
| J | Replay deterministic + idempotent | PASS | `test_database_rows_equal_parser_output`, `test_replay_twice_is_idempotent`, the session variant, interrupted → re-replay |
| K | Full suite green | PASS | 254 passed (the count was 203 at the start of this work) |
| L | Real trading-day end-to-end | **FAIL (pending)** | source → archive → parser → DB → replay has run on synthetic and fake-server data only. The live smoke wrote archives but no DB rows |
| M | No V1 DB or code path | PASS | `app/` references V1 only in the deny-list (`FORBIDDEN_DATABASES`) and comments; tested by `tests/unit/test_guards.py` and `test_vendor_purity.py`; `prajna_rw` has no rights outside its DBs |
| N | Unknowns resolved or removed | **FAIL** | see the open list below |

---

## Implementation evidence (commits, oldest first, this stage)

| Commit | What |
|---|---|
| `51709bd` | M0 foundation (isolation, contracts, schema, provenance, archive, 81 tests) |
| `725e294` | Upstox token mint/probe |
| `616a717` | PostgreSQL 18 in Docker (loopback) |
| `8154e2b` | pinned proto, frame archive, feed parser, replay |
| `f09b412` | pre-open WebSocket recorder |
| `eeac6d1` | universe selection from the instrument master |
| `0049cda` | watchdog fix and first live smoke results (B3, B5, B6) |
| `58ccdae` | multi-connection capture (2 × ≤2,000) |
| `8f95cc4` | M2 session calendar |
| `13ddb9c` | acceptance harness and failure/recovery tests |

## Real-market evidence so far

| Evidence | Where | Hash (prefix) |
|---|---|---|
| Instrument master, 80,226 rows, 3,525 eligible | `var/archive/UPSTOX_ASSETS/2026/09/23/` | `bf4a5db89c9e` |
| Holidays 2026 (22 entries) | `var/archive/UPSTOX_REST_V2/…`, fixture `holidays_2026.json` | `eff843d4995d` |
| Timings 2026-09-24 (NORMAL) | same; fixture | `c8ee15cb1d42` |
| 100 timings payloads 2026-09-23..12-31 | `var/archive/UPSTOX_REST_V2/2026/09/23/` | 73 distinct payloads in `raw_payload` |
| WS smoke: full / 5 keys | `preopen_2026-09-23_080536Z.frames.gz` | stream `589f3ebf3676` |
| WS smoke: full_d30 / 5 keys (ignored) | `…_080738Z.frames.gz` | `90b49d2744f5` |
| WS smoke: 3,525 on one connection (2,000 served) | `…_080926Z.frames.gz` | `099f30c5edf5` |
| WS smoke: 2 concurrent connections (2,000 + 1,525, all served) | `…_081059Z`, `…_081101Z` | `229af0d10163`, `407314ff0693` |

Details: `docs/2026-09-23_M1_LIVE_SMOKE.md`.

## Database counts (`prajna`, at the time of writing)

| Table | Rows |
|---|---|
| trading_session | 100 |
| raw_payload | 73 |
| ingest_run | 3 (calendar COMMIT, calendar DRY_RUN, universe DRY_RUN) |
| ingest_anomaly | 1 (COVERAGE_CAP from the pre-sharding universe dry run) |
| instrument_universe_membership | 0 (the universe is committed on the morning of capture) |
| preopen_tick / book / status | 0 (the smoke did not replay) |
| instrument, ohlcv_bar, corporate_action, fundamental_snapshot, macro_observation, news_article, tick_archive | 0 (not implemented) |

## Coverage statistics

- **Eligible universe:** 3,525. EQ 2,670 · SM 467 · BE 237 · ST 103 · BZ 27 · IV 21. ISIN prefixes: INE 3,172 · INF 351 · IN9 2.
- **Capture plan:** 2 connections, 2,000 + 1,525 keys; 0 excluded by capacity. The 2,000-per-connection limit and 2 concurrent connections were **measured**; more than 2 connections is untested.
- **Live smoke coverage:** 3,525/3,525 keys produced frames across the 2 concurrent connections.

## Known limitations

- **Pre-open boundaries:** Upstox does not publish them. 09:00–09:15 is derived for NORMAL sessions; special sessions (Budget Sunday, Muhurat) have **no** pre-open window recorded, and the runbook refuses them.
- **30-rung depth:** not available to this account (B3, inferred); 5 rungs is the ceiling.
- **Presence of zero:** proto3 cannot distinguish `iep = 0` from "not sent" (B8 context).
- **Holiday coverage:** the holiday list covers 2026 only; 2027 needs a fetch after Upstox publishes it.
- **Instrument history:** the instrument master is used for selection only; the SCD2 `instrument` table (history, renames) is not populated (M3).
- **Local network:** intermittent TLS hostname mismatches and resets. The recorder retries with verification intact; this can cost ~30–40 s of a window.
- **Duplicate snapshots before 09:00:** the recorder reconnects every stale period until pre-open data flows. Each reconnect's `initial_feed` is archived as a genuine observation at its own `currentTs`.

## Unresolved blockers and decisions

| ID | Item | Resolution path |
|---|---|---|
| B0 | Token expires daily ~03:30 IST | the runbook's `--login`, or the user logs in |
| B1 / B2 | Bar finalisation and publication lag | M4 measurement |
| B3 | full_d30 | inferred unavailable; confirm with Upstox or accept 5 rungs |
| B4 | FII/DII from Upstox | **RESOLVED 2026-09-23:** Upstox serves it; in scope; ingested (4,760 rows). See the M4 live validation doc §13 |
| B7 | iiqM semantics | real pre-open day → harness `B7.observation` → human reading |
| B8 | IEP/IEQ/IIQ population | real pre-open day → harness `B8` |
| B10 | Special-session pre-open windows | observe on the next special session, or leave out of scope |
| P1 | WS knowable_at vs fetched_at | user decision (matrix §PIT) |
| S1 | Series policy: REIT (RR), D1/E1/IT/SZ/W1 | user decision |
| S2 | Scope: corporate actions, fundamentals, news, global/macro, all-day ticks | user decision: implement (with a verified Upstox endpoint) or remove from Stage 1 with justification |

## What makes this document say COMPLETE

1. **A real trading day.** `ops/runbooks/preopen_day.sh 2026-09-24` exits 0,
   and `var/acceptance/preopen_2026-09-24.json` shows:
   - `real_market_data: true`,
   - verdict PASS/WARN,
   - B8 RESOLVED,
   - B7 OBSERVED and interpreted.

   That settles H and L.
2. **Scope decisions S1, S2 and P1 are made.** Each source that stays in scope
   is implemented to the §2 standard, with a verified Upstox endpoint. That
   settles A and N.
3. **This document is regenerated** with the new evidence and commit hashes.
