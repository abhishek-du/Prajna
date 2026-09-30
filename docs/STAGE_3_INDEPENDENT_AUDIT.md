# Stage 3 Independent Audit & Verification Report

**Document:** `docs/STAGE_3_INDEPENDENT_AUDIT.md`  
**Date:** 2026-09-28T19:05:00+05:30  
**Auditor:** Independent Auditor & Verification Engineer  
**Audit Standard:** Strict Empirical Verification — Zero Assumptions, Evidence-First  
**Repository:** `/home/cis/windows/prajna`  
**HEAD Commit:** `0fa483948404c32b78523df885acbf1fe7fbcd61`  

---

## 1. Executive Summary

An exhaustive, independent verification and audit of the Prajna trading-data system was conducted across Stage 1, Stage 2, and Stage 3. The audit evaluated code contracts, database schema, transaction isolation, live database state, acceptance gates, regression test suites, point-in-time constraints, and runtime performance on real market data (3,547 instruments).

### Core Audit Verdict

**FINAL STATUS:** **NOT PRODUCTION READY — FAILURES FOUND**

While the mathematical indicator computations, point-in-time boundaries, and acceptance gates have reached advanced maturity (`prajna acceptance stage3` evaluates to level `PRODUCTION READY` with criteria A–N passing and O pending), an **independently executed real-data persistence benchmark uncovered a critical blocker in the execution engine**:

1. **CRITICAL DEFECT — BATCH INSERT PARAMETER OVERFLOW (`BUG-STAGE3-PERSIST-PARAM-LIMIT`):**  
   In [`app/features/engine.py`](file:///home/cis/windows/prajna/backend/app/features/engine.py#L330-L333), `persist()` chunks rows into batches of 5,000. Each `feature_value` row contains 15 parameterized attributes ($5,000 \times 15 = 75,000$ bind parameters). PostgreSQL and `asyncpg` enforce an architectural hard limit of 32,767 query parameters per statement. When executed against the real active universe of 3,547 instruments (180,919 feature rows), the persistence transaction crashes with:  
   `asyncpg.exceptions._base.InterfaceError: the number of query arguments cannot exceed 32767`.  
   Because unit tests only evaluated a toy fixture of 5 stocks ($\approx 275$ rows), this bug remained hidden until this audit tested persistence on the full universe. Any committed production execution on the full universe will fail.

2. **OPERATIONAL DEFECT — CLI WORKING DIRECTORY PATH SENSITIVITY (`BUG-STAGE1-CLI-CWD-RELATIVE-PATHS`):**  
   [`app/acceptance/stage1.py`](file:///home/cis/windows/prajna/backend/app/acceptance/stage1.py#L344) hardcodes relative paths (`var/acceptance/preopen_*.json`, `var/acceptance/b1b2.json`, `var/logs/daily/...`). When executed from the repository root, Stage 1 acceptance reports `OVERALL: NOT COMPLETE` (K fails, R and X wait). It succeeds as `COMPLETE` only when current working directory is explicitly set to `backend/`.

3. **SCHEDULE GAP (`DOC-GAP-SCHEDULE`):**  
   `backend/ops/cron/prajna.cron` references `docs/STAGE_3_PRODUCTION_SCHEDULE.md`, but this document does not exist in the repository, and decision `SCHEDULE` remains `PENDING_APPROVAL`.

### Summary of Audited Stages

| Stage / Subsystem | Claimed Status | Verified Status | Key Findings |
|---|---|---|---|
| **Stage 1 (Raw Ingestion)** | COMPLETE | **VERIFIED COMPLETE** (with backend Cwd) | 21 criteria PASS; 4 DEFERRED by approved decision `BACKFILL-DEFER` (G, I, J, S); 2 OUT_OF_SCOPE (H, L). 150 tests pass. |
| **Stage 2 (Point-in-Time)** | PASS | **VERIFIED PASS** | 16/16 criteria PASS. Full test suite (1,104 passed, 2 skipped in 330.11s). Zero look-ahead leakage across real database probes. |
| **Stage 3 Registry** | 65 features | **VERIFIED** | 65 features registered under `features-v1` across 6 groups. All 31 diagram items mapped and accounted for. |
| **Stage 3 Decisions** | Approved | **VERIFIED** | `FEATURE-SCOPE`, `FEATURE-PARAMS`, `FII-DII-STALENESS`, `FEATURE-SNAPSHOTS`, and `FEATURE-NO-SOURCE` are all approved. |
| **Stage 3 Engine & PIT** | Ready | **VERIFIED PIT / CRITICAL DEFECT ON PERSIST** | PIT safety, REPEATABLE READ isolation, idempotency, determinism, and lock enforcement pass; batch persistence crashes on full universe. |
| **Stage 3 Acceptance Gate** | PRODUCTION READY | **VERIFIED PRODUCTION READY (Dry-Run)** | Criteria A–N PASS; O PENDING (production empty); Level reached: `PRODUCTION READY`. Level not reached: `PRODUCTION UNLOCKED`. |
| **Multi-Source News** | Separate / Locked | **VERIFIED SEPARATED** | `mnews_*` quarantined in `news_features.py`; decision `FEATURE-NEWS-V2` is PENDING; 0 rows in production. |
| **Production Safety** | Strictly Locked | **VERIFIED LOCKED** | `feature_value` = 0 rows; Stage 3 `ingest_run` = 0; flags disabled; kill switch inactive; no cron/systemd installed. |

---

## 2. Repository Baseline

The baseline repository state was established before running audit evaluations:

- **Repository Root:** `/home/cis/windows/prajna`
- **Active Branch:** `main`
- **HEAD Commit:** `0fa483948404c32b78523df885acbf1fe7fbcd61` (`stage3: add adversarial PIT coverage`)
- **Working Tree Cleanliness:** Clean working tree except for uncommitted comments in `backend/ops/cron/prajna.cron` (uncommented Stage 3 cron templates marked `PENDING_APPROVAL`).
- **Python / Runtime:** `Python 3.11.16` (uv managed cpython-3.11-linux-x86_64-gnu at `/home/cis/windows/prajna/backend/.venv/bin/python`).
- **Database Topology:**
  - Production Database: `postgresql+asyncpg://prajna_rw:***@localhost:5432/prajna` (Alembic revision `0014`)
  - Test Database: `postgresql+asyncpg://prajna_rw:***@localhost:5432/prajna_test` (Alembic revision `0014`)
- **Stage 3 Core Commit History:**
  - `c36d81e`: `stage3: feature registry and pure feature computations`
  - `b4972f8`: `stage3: feature storage, engine and execution locks`
  - `c54816d`: `stage3: CLI and read API surfaces (stored values only)`
  - `4d34c1b`: `stage3: acceptance gate with readiness levels, and the design document`
  - `4e8c822`: `stage3: record the user's approval of FEATURE-PARAMS`
  - `8b612e0`: `stage3: ready-for-unlock review (not yet ready: Stage 1 X pending)`
  - `580f587`: `stage3: enforce fii-dii staleness (decision FII-DII-STALENESS, approved)`
  - `c42cb0d`: `stage3: use repeatable read snapshot`
  - `0fa4839`: `stage3: add adversarial PIT coverage` (HEAD)
- **Baseline Evidence File:** [`audit/evidence/BASELINE.md`](file:///home/cis/windows/prajna/audit/evidence/BASELINE.md)

---

## 3. Stage 1 Verification

### Audit Method
Stage 1 acceptance was independently executed using the official repository command from both the root workspace and the `backend/` working directory, followed by unit and integration regression test suites.

### Execution Results
- **Command (backend directory):**  
  `.venv/bin/prajna acceptance stage1 --out /home/cis/windows/prajna/audit/evidence/stage1_run_backend_cwd.json --md /home/cis/windows/prajna/audit/evidence/STAGE_1_ACCEPTANCE_FROM_BACKEND.md`
- **Exit Code:** `0`
- **Generated Report:** [`audit/evidence/STAGE_1_ACCEPTANCE_FROM_BACKEND.md`](file:///home/cis/windows/prajna/audit/evidence/STAGE_1_ACCEPTANCE_FROM_BACKEND.md)
- **JSON Evidence:** [`audit/evidence/stage1_run_backend_cwd.json`](file:///home/cis/windows/prajna/audit/evidence/stage1_run_backend_cwd.json)

### Criteria Evaluation Matrix (A–Y)

| ID | Criterion | Status | Verified Result / Evidence |
|---|---|---|---|
| **A** | Database isolation | **PASS** | Current database `prajna`; V1 `autotrade_pro` never used. |
| **B** | Provenance | **PASS** | 0 orphan rows, 0 bad runs, 0 missing basis across 6.37M bars and macro/news tables. |
| **C** | Point-in-time safety | **PASS** | $knowable\_at \le fetched\_at$: 0 violations across all 11 tables. |
| **D** | Instrument master | **PASS** | Active NSE EQ: 3,544; sector present for 3,171/3,171 eligible stocks (100.0% coverage); review: 0. |
| **E** | Trading calendar | **PASS** | 2,557 days (2020-01-01 to 2026-12-31); contiguous; matches NIFTY 50 trading sessions. |
| **F** | 1D candles | **PASS** | 3,547 active instruments covered to depth; 3,686,469 bars; 265 quarantined (Q1). |
| **G** | 1m candles (last 6 months) | **DEFERRED** | Postponed by approved decision `BACKFILL-DEFER` (live 1m tracked under R). |
| **H** | 5m candles | **OUT_OF_SCOPE** | Excluded from Stage 1 by approved decision `D2-5m`. |
| **I** | 15m candles (from 2022) | **DEFERRED** | Postponed by approved decision `BACKFILL-DEFER` (live 15m tracked under R). |
| **J** | 1h candles (from 2022) | **DEFERRED** | Postponed by approved decision `BACKFILL-DEFER` (live 1h tracked under R). |
| **K** | Pre-open capture | **PASS** | 1,161,842 ticks; 3 sessions captured; 0 trading sessions missed. |
| **L** | Live WebSocket persistence | **OUT_OF_SCOPE** | All-day persistence deferred to Stage 7 by approved decision `D5`. |
| **M** | Corporate actions | **PASS** | 2,323 events across 1,553 ISINs; 3,545 ISINs swept. |
| **N** | News | **PASS** | 197 articles, 604 links swept; latest sweep 2026-09-28 10:01 UTC. |
| **O** | Fundamentals | **PASS** | 41,785 snapshots across 3,545 instruments; 12 statement types. |
| **P** | FII/DII | **PASS** | 6 streams active; observations through 2026-09-25. |
| **Q** | Global / Macro | **PASS** | 13 global instruments meet per-instrument finality contract. |
| **R** | Daily incremental ingestion | **PASS** | 1m/15m/1h complete on 2026-09-24 and 2026-09-25; rerun checks confirmed idempotent. |
| **S** | Historical backfill depth | **DEFERRED** | 1D depth (F) PASS; intraday depth deferred by `BACKFILL-DEFER`. |
| **T** | Replay & raw archive hashes | **PASS** | 125 sampled runs replayed with 0 mismatches; 69,535 file payloads and 34,379 frame payloads verified with 0 SHA-256 mismatches. |
| **U** | Idempotency | **PASS** | 0 natural key duplicates across macro, news, corporate actions, fundamentals. |
| **V** | Crash recovery | **PASS** | 0 stale running runs; rollback and resume unit tests pass. |
| **W** | Coverage reconciliation | **PASS** | 0 NSE 1D streams without outcome. |
| **X** | Look-ahead & Timing (B1/B2) | **PASS** | 0 look-ahead violations; B1 verified over 3 sessions (09-23, 09-24, 09-25); revised B2 verified over 3 sessions (09-24, 09-25, 09-28). |
| **Y** | Survivorship policy | **PASS** | Survivorship bias documented and accepted under approved decision `SURV`. |

### Decision Logic and Gate Analysis
- **Definition of COMPLETE:** In [`backend/app/acceptance/stage1.py`](file:///home/cis/windows/prajna/backend/app/acceptance/stage1.py#L648-L649), `settled = (PASS, OUT_OF_SCOPE, DEFERRED)`. An overall status of `COMPLETE` is achieved if and only if every criterion is in `settled`. Because G, I, J, and S are approved `DEFERRED`, and H and L are approved `OUT_OF_SCOPE`, they legitimately fulfill the contract.
- **Is Today's Close Required?** No. `_latest_session()` resolves the latest trading session strictly before current date (`2026-09-25`). Criterion R requires at least one previous complete session with idempotent rerun evidence, which is satisfied by both `2026-09-24` and `2026-09-25`.
- **Stage 1 Test Suite:** 150 passed in 1.16s (`pytest tests/unit/test_stage1_x_decision.py tests/integration/test_stage1_acceptance.py tests/contracts/ tests/unit/test_analyze_timing.py`).

---

## 4. Stage 2 Verification

### Audit Method
Stage 2 acceptance was executed with `--run-tests` to run the full regression test suite alongside database point-in-time assertions.

### Execution Results
- **Command:** `.venv/bin/prajna acceptance stage2 --run-tests --out /home/cis/windows/prajna/audit/evidence/stage2_run.json --md /home/cis/windows/prajna/audit/evidence/STAGE_2_ACCEPTANCE_RUN.md`
- **Exit Code:** `0`
- **Overall Verdict:** `PASS`
- **Generated Report:** [`audit/evidence/STAGE_2_ACCEPTANCE_RUN.md`](file:///home/cis/windows/prajna/audit/evidence/STAGE_2_ACCEPTANCE_RUN.md)
- **JSON Evidence:** [`audit/evidence/stage2_run.json`](file:///home/cis/windows/prajna/audit/evidence/stage2_run.json)

### Criteria Evaluation Matrix (A–P)

| ID | Criterion | Status | Empirical Evidence |
|---|---|---|---|
| **A** | Process Stage 1 data | **PASS** | Latest commit run mode NOOP (0.59s); 3,548 included instruments; 14,192 coverage pairs; 113,517 coverage ranges. |
| **B** | Data normalization | **PASS** | 0 duplicate bars; 0 invalid timeframes; 0 null required bar fields; 0 coverage contradictions. |
| **C** | Timestamp integrity | **PASS** | 0 bars knowable before event end; 0 daily bars fetched same session; daily label 00:00 IST. |
| **D** | Preservation of knowable_at | **PASS** | 0 canonical vs Stage 1 mismatches; 0 knowable after fetched. |
| **E** | Point-in-time leakage | **PASS** | Real database probes: 40 instruments tested at random boundary timestamps; 40/40 boundary behavior correct; 40/40 coverage point-in-time consistent. |
| **F** | NSE filtering | **PASS** | 0 non-NSE included; 0 global included; rules SHA `911fa7ab...` consistent. |
| **G** | Instrument mapping | **PASS** | 0 mapping mismatches; 0 orphans; 0 missing identifiers. |
| **H** | Data enrichment traceability | **PASS** | 3,192 instruments with sector traceable to fundamental snapshots via `pit.sector()`. |
| **I** | Missing data representation | **PASS** | Explicit coverage states: 3.68M DATA, 2.27M EMPTY, 8.74M PENDING_BACKFILL; no zero-filling or forward-filling. |
| **J** | Quarantine handling | **PASS** | 2 quarantined bars excluded; 69 non-session placeholder bars excluded; 0 invalid OHLC exposed. |
| **K** | Idempotency | **PASS** | Three consecutive real NOOP reruns produce 0 inserts. |
| **L** | Crash recovery | **PASS** | `test_crash_rolls_back_and_the_rerun_resumes` passes; 0 failed canonical runs. |
| **M** | Incremental processing | **PASS** | Real incremental runs touch only new pairs; `test_incremental_update_touches_only_the_new_pair` passes. |
| **N** | Database constraints | **PASS** | All 11 expected constraints (`ck_canon_instrument_nse_only`, `ck_ohlcv_sane`, `ck_ohlcv_knowable`, etc.) enforced. |
| **O** | Safe Stage 3 consumption | **PASS** | 10/10 sampled instruments safely queried across daily bars, corporate actions, news, fundamentals, sector. |
| **P** | Existing tests passing | **PASS** | Full test suite passed: **1,104 passed, 2 skipped in 330.11s (0:05:30)**. |

---

## 5. Stage 3 Registry Verification

### Audit Method
Inspected [`backend/app/features/registry.py`](file:///home/cis/windows/prajna/backend/app/features/registry.py), [`backend/app/features/engine.py`](file:///home/cis/windows/prajna/backend/app/features/engine.py), and [`backend/app/features/audit_doc.py`](file:///home/cis/windows/prajna/backend/app/features/audit_doc.py).

### Registry Metrics
- **Registry Version:** `features-v1`
- **Registry Hash:** `9061d85b3696ab70e566d8257ecb13466930792a74f9b1d8308f232331e47188`
- **Total Features:** Exactly 65 features.
- **Implemented Features:** 65 features.
- **Diagram Coverage:** 31 diagram items mapped across 6 diagram groups:
  - 22 IMPLEMENTED
  - 5 PARTIAL (documented with specific omissions: support/resistance levels beyond 20 sessions, bid-ask spread, balance sheet debt, news sentiment, gap up/down vs IEP)
  - 3 UNSUPPORTED (order book imbalance, earnings surprises, analyst ratings — missing data sources named)
  - 1 UNKNOWN (market regime — no standard definition in any source)

### Group Breakdown
1. **Price & Technical (23 features):** `ret_1d`, `ret_5d`, `ret_20d`, `sma_20`, `sma_50`, `sma_200`, `close_to_sma_20`, `close_to_sma_50`, `close_to_sma_200`, `ema_12`, `ema_26`, `rsi_14`, `macd_line`, `macd_trigger`, `macd_histogram`, `atr_14`, `atr_pct_14`, `volatility_20`, `beta_60`, `dist_high_20`, `dist_low_20`, `breakout_20`, `breakdown_20`.
2. **Volume & Liquidity (3 features):** `avg_volume_20`, `volume_spike_20`, `turnover_20`.
3. **Fundamental (13 features):** `pe`, `pb`, `roe_pct`, `roce_pct`, `ev_ebitda`, `pe_to_sector`, `pb_to_sector`, `revenue_yoy`, `pat_yoy`, `eps_yoy`, `revenue_yoy_q`, `pat_yoy_q`, `liabilities_to_assets`.
4. **Event (11 features):** `ca_days_since_any`, `ca_days_since_dividend`, `ca_days_since_split`, `ca_days_since_bonus`, `ca_days_to_any`, `ca_days_to_dividend`, `ca_days_to_split`, `ca_days_to_bonus`, `news_count_24h`, `news_count_7d`, `news_hours_since_last`.
5. **Market Context (11 features):** `index_ret_1d`, `index_ret_5d`, `index_close_to_sma_50`, `india_vix_level`, `india_vix_change_5d`, `fii_net_cash_1d`, `fii_net_cash_5d`, `dii_net_cash_1d`, `dii_net_cash_5d`, `global_ret_1d`, `sector_rs_20`.
6. **Pre-Open (4 features):** `preopen_gap_pct`, `preopen_imbalance`, `preopen_ieq`, `preopen_ieq_to_avg_volume`.

---

## 6. Feature Parameter Verification

### Audit Method
Inspected [`backend/app/features/decisions.py`](file:///home/cis/windows/prajna/backend/app/features/decisions.py#L12-L22) and verified against `app/features/registry.py`.

### Decision Record
- **Decision ID:** `FEATURE-PARAMS`
- **Status:** `APPROVED`
- **Date & Reference:** 2026-09-28 (`user 2026-09-28 ('Conventional, pending approval'; then 'approve the proposed feature params')`)
- **Configured Parameter Values in Code:**
  - `SMA`: 20, 50, 200 (`sma_20`, `sma_50`, `sma_200`, `close_to_sma_20`, `close_to_sma_50`, `close_to_sma_200`)
  - `EMA`: 12, 26 (`ema_12`, `ema_26`)
  - `RSI`: 14 periods, Wilder smoothing (`rsi_14`)
  - `MACD`: Fast 12, Slow 26, Signal 9 (`macd_line`, `macd_trigger`, `macd_histogram`)
  - `ATR`: 14 periods, Wilder smoothing (`atr_14`, `atr_pct_14`)
  - `Volatility`: 20 sessions, 252 annualisation (`volatility_20`)
  - `Beta`: 60 sessions against benchmark `NSE_INDEX|Nifty 50` (`beta_60`)
  - `Range / Breakout`: 20 sessions (`dist_high_20`, `dist_low_20`, `breakout_20`, `breakdown_20`)
  - `Volume / Liquidity`: 20 sessions (`avg_volume_20`, `volume_spike_20`, `turnover_20`)
  - `Index SMA`: 50 sessions (`index_close_to_sma_50`)
  - `India VIX`: 5 sessions change (`india_vix_change_5d`)
  - `FII/DII Net Flow`: 5 sessions sum (`fii_net_cash_5d`, `dii_net_cash_5d`)
  - `Sector RS`: 20 sessions, minimum 3 members in sector (`sector_rs_20`)
  - `Pre-Open IEQ`: 20 sessions average volume comparison (`preopen_ieq_to_avg_volume`)

---

## 7. FII/DII Staleness Verification

### Audit Method
Inspected [`backend/app/features/compute/context.py`](file:///home/cis/windows/prajna/backend/app/features/compute/context.py#L63-L77), [`backend/app/features/engine.py`](file:///home/cis/windows/prajna/backend/app/features/engine.py#L225-L230), and [`backend/app/features/decisions.py`](file:///home/cis/windows/prajna/backend/app/features/decisions.py#L23-L32) (decision `FII-DII-STALENESS`). Executed an automated 9-case test harness in Python saving raw results to [`audit/evidence/PHASE_5_FII_DII_EVIDENCE.json`](file:///home/cis/windows/prajna/audit/evidence/PHASE_5_FII_DII_EVIDENCE.json).

### Test Suite Results

```json
{
  "1_previous_session": {"expected": [60.0, null], "actual": [60.0, null], "pass": true},
  "2_older_observation": {"expected": [null, "MISSING_INPUT"], "actual": [null, "MISSING_INPUT"], "pass": true},
  "3_holiday_boundary": {"expected": [50.0, null], "actual": [50.0, null], "pass": true},
  "4_late_publication": {
    "before_as_of": {"expected": [null, "MISSING_INPUT"], "actual": [null, "MISSING_INPUT"], "pass": true},
    "after_as_of": {"expected": [50.0, null], "actual": [50.0, null], "pass": true}
  },
  "5_publication_after_as_of": {"expected": [null, "MISSING_INPUT"], "actual": [null, "MISSING_INPUT"], "pass": true},
  "6_missing_observation": {"expected": [null, "MISSING_INPUT"], "actual": [null, "MISSING_INPUT"], "pass": true},
  "7_insufficient_history": {
    "1d": {"expected": [30.0, null], "actual": [30.0, null], "pass": true},
    "5d": {"expected": [null, "INSUFFICIENT_HISTORY"], "actual": [null, "INSUFFICIENT_HISTORY"], "pass": true}
  },
  "8_5d_window_ending_early": {"expected": [null, "MISSING_INPUT"], "actual": [null, "MISSING_INPUT"], "pass": true},
  "9_malformed_data": {
    "one_sided": {"expected": [null, "MALFORMED_INPUT"], "actual": [null, "MALFORMED_INPUT"], "pass": true},
    "non_numeric": {"expected": [null, "MALFORMED_INPUT"], "actual": [null, "MALFORMED_INPUT"], "pass": true}
  }
}
```

**Verdict:** **VERIFIED**. Version 2 of FII/DII features enforces that the latest observation must match `snapshot.previous_session` exactly. Older observations are never relabelled as current.

---

## 8. Point-in-Time Safety Verification

### Audit Method
Audited `test_engine.py::TestPointInTime` (4 tests) and `test_engine.py::TestAdversarialPointInTime` (5 tests). All 9 tests passed.

### Test Verifications
1. **Facts Known Exactly At / After as_of:** Injected facts (bars, fundamental snapshots, news articles, preopen ticks) with $knowable\_at = as\_of$. Computed features showed 0 change against baseline (`test_look_ahead_probe`).
2. **Microsecond Boundary Exclusion:** Injected P/E at $as\_of - 1\mu s$ and $as\_of$. Only the $as\_of - 1\mu s$ value was used (`test_knowable_boundary_one_microsecond`).
3. **Late Intraday Bar Revision:** Re-served bar with different close at $as\_of - 1h$ and $as\_of + 30m$. The first observation remained visible; revision in `ohlcv_observation` was ignored (`test_late_bar_revision_is_never_used`).
4. **Corporate Action Revised After as_of:** Bonus ratio revised from 1:1 to 2:1 knowable at 09:05. At PRE_SESSION (08:59:59), only the 1:1 ratio was used. At PRE_OPEN (09:08:00), the 2:1 ratio was recognized (`test_revised_corporate_action_known_after_as_of`).
5. **Delayed Financial Statement:** June 2026 quarter knowable at 09:05. Invisible at PRE_SESSION (`MALFORMED_INPUT`); visible at PRE_OPEN (`test_delayed_financial_statement`).
6. **India VIX Previous Session Missing:** VIX bar for previous session missing at PRE_SESSION $\rightarrow$ `MISSING_INPUT`; arrived before PRE_OPEN $\rightarrow$ populated (`test_india_vix_previous_session_missing`).
7. **Database Constraint:** `ck_feature_pit` enforces `input_max_knowable_at is null or input_max_knowable_at < as_of`. Attempted inserts with $knowable\_at \ge as\_of$ fail at SQL level.

---

## 9. Transaction Consistency Verification

### Audit Method
Inspected transaction lifecycle in [`backend/app/features/engine.py`](file:///home/cis/windows/prajna/backend/app/features/engine.py#L98-L120) and tested concurrent modification isolation on `prajna_test` (`TestSnapshotConsistency`).

### Findings
- **Isolation Level:** `consistent_read()` sets `set transaction isolation level repeatable read` (and `, read only` for dry runs).
- **Run Record Sequence:** The `ingest_run` row is created and committed first in its own transaction (line 363). Then `consistent_read(s, read_only=False)` begins the main computation transaction.
- **Concurrent Canon Commit:** Verified empirically in `test_a_commit_during_the_run_is_not_observed`: Transaction A begins, Transaction B commits new FII/DII data mid-run, Transaction A continues and reads from its original snapshot. It does not observe Transaction B's commit.
- **Enforcement:** If an enclosing session is at `READ COMMITTED`, `consistent_read` raises `SnapshotIsolationError` and refuses execution (`test_a_run_refuses_without_a_consistent_snapshot`).

---

## 10. Atomicity & Idempotency Verification

### Audit Method
Audited `test_engine.py::TestRun` (8 tests) in `prajna_test`.

### Findings
- **Single Snapshot Atomicity:** Features are staged in memory and persisted into `feature_value` within the single `REPEATABLE READ` transaction. Commit occurs only after determinism verification passes and run finalization completes.
- **Rollback on Failure:** Simulated disk error during `persist()`. Database state verified: exactly 0 feature rows committed (`test_exception_rolls_back_then_retry_succeeds`).
- **Idempotent Reruns:** Executing `run_snapshot` twice on the same session/snapshot inserts rows on first run, and on the rerun reports `inserted=0, already_present=N`. No duplicate rows created (`uq_feature_value` constraint).
- **Determinism Protection:** Backdating a fundamental ratio for an already-computed session causes recompute to detect discrepancy and raise `DeterminismMismatch`. The existing row is never overwritten (`test_determinism_mismatch_never_overwrites`).
- **Crash Recovery & Reaper:** Simulated crashed runner PID. Reaper marked run `ABORTED`. Subsequent rerun resumed and completed cleanly (`test_crash_is_reaped_and_the_rerun_completes`).

---

## 11. Lock Verification

### Audit Method
Audited [`backend/app/features/locks.py`](file:///home/cis/windows/prajna/backend/app/features/locks.py) and executed `test_engine.py::TestLocks` (9 tests).

### Lock Enforcement Hierarchy
Lock enforcement is implemented directly within `app/features/engine.py::run_snapshot` via `await locks.require(s, mode=mode, token=token)` (lines 354, 159–168). It cannot be bypassed by calling the engine directly without the CLI.

| Condition | Tested Breach | Result | Audit Log |
|---|---|---|---|
| `stage3_enabled` | `PRAJNA_STAGE3_ENABLED=false` | REFUSED (PermissionError) | Event `REFUSED` in `stage3_event` |
| `kill_switch_off` | `var/run/stage3.kill` created | REFUSED (PermissionError) | Event `REFUSED` in `stage3_event` |
| `stage1_complete` | Stage 1 reported NOT COMPLETE | REFUSED (PermissionError) | Event `REFUSED` in `stage3_event` |
| `stage2_pass` | Stage 2 reported FAIL | REFUSED (PermissionError) | Event `REFUSED` in `stage3_event` |
| `decisions_approved` | Decision `FEATURE-PARAMS` set to PENDING | REFUSED (PermissionError) | Event `REFUSED` in `stage3_event` |
| `write_token` | Token invalid or omitted | REFUSED (PermissionError) | Event `REFUSED` in `stage3_event` |
| `backfill_enabled` | `PRAJNA_STAGE3_BACKFILL_ENABLED=false` | REFUSED on BACKFILL mode | Event `REFUSED` in `stage3_event` |
| Mid-Run Kill Switch | Kill switch engaged during computation loop | Aborted mid-run (`KillSwitchEngaged`), 0 rows committed | Event `RUN_FAILED` in `stage3_event` |

---

## 12. Production Database State

### Audit Method
Performed read-only SQL inspection on the production database (`prajna`) via `backend/.venv/bin/python`.

### Findings
- **Database Name:** `prajna`
- **Alembic Revision:** `0014`
- **`feature_value` Table Row Count:** **0**
- **`ingest_run` (`stream like 'features.%'`):** **0**
- **`stage3_event` Table Row Count:** **4**  
  (All 4 events are historical `REFUSED` audit records from CLI lock validation attempts: ID 1 & 3 for `RUN`, ID 2 & 4 for `BACKFILL`).
- **Environment Flags:** Neither `PRAJNA_STAGE3_ENABLED` nor `PRAJNA_STAGE3_BACKFILL_ENABLED` is present in `backend/.env`.
- **Kill Switch File (`backend/var/run/stage3.kill`):** Absent.

---

## 13. Runtime Verification & Performance

### Audit Method
Executed real-data measurement of the active universe (3,547 instruments) on session `2026-09-28` for snapshot `PRE_SESSION` using `consistent_read(s, read_only=True)`.

### Empirical Results
- **Active Universe:** **3,547 instruments**
- **Pure Computation Runtime:** **137.16 seconds** ($\approx 2\text{ min } 17\text{ s}$)
- **Total In-Memory Generation Time:** **137.30 seconds**
- **Features / Rows Evaluated:** **180,919 feature rows**
- **Values Computed:** 128,944 values
- **Null Reasons:**
  - `MISSING_INPUT`: 42,779
  - `MALFORMED_INPUT`: 4,567
  - `INSUFFICIENT_HISTORY`: 3,480
  - `DIVISION_UNDEFINED`: 1,149
- **Refused Low-Confidence Bars:** 154,618 bars (older than corporate-action horizon)
- **Claimed PRE_SESSION Benchmark:** 142 seconds
- **Reproducibility Verdict:** **CONFIRMED REPRODUCIBLE (Computation Phase)**.  
  The pure computation time of 137.16 seconds directly reproduces the claimed $\approx 140$ second runtime and disproves the initial 50–60 minute estimate.

### Persistence Defect Discovery
When the benchmark proceeded to test `persist()` into the test database (to measure persistence overhead), it crashed:
`asyncpg.exceptions._base.InterfaceError: the number of query arguments cannot exceed 32767`.  
See Section 19 (`BUG-STAGE3-PERSIST-PARAM-LIMIT`).

---

## 14. Schedule Verification

### Proposed Timing Compatibility
- **PRE_SESSION Snapshot:**
  - `as_of`: 08:59:59 IST
  - Proposed start: 09:00:30 IST
  - Runtime: $\approx 137\text{ s}$ compute $+$ estimated $15\text{ s}$ persistence $\approx 152\text{ s}$ ($\approx 2.5\text{ min}$)
  - Expected completion: $\approx 09:03:02\text{ IST}$ (well before 09:15:00 open). Compatible.
- **PRE_OPEN Snapshot Trade-Off:**
  - `as_of`: 09:08:00 IST
  - **Option A (09:08:30 start):** Finishes at $\approx 09:11:15\text{ IST}$ (before open), BUT because `preopen_day.sh` captures until 09:20 and replays at 09:20–09:33, all 4 `preopen_*` features evaluate to `MISSING_INPUT`.
  - **Option B (09:21:00 start with `--after-replay`):** Pre-open features are populated, but computation finishes at $\approx 09:36\text{ IST}$ (after 09:15:00 market open).
- **Schedule Installation State:**
  - System crontab (`crontab -l`): Stage 3 is NOT installed.
  - Systemd: No Stage 3 units or timers installed.
  - Cron template (`backend/ops/cron/prajna.cron`): All Stage 3 entries are commented out with `# PENDING_APPROVAL: ...`.

---

## 15. 65-Feature Audit Matrix

All 65 features registered in `features-v1` were audited against their mathematical specifications, data sources, lookback windows, corporate action handling, and test evidence:

| # | Feature ID | Group | Scope | Lookback | Inputs | Parameters | PIT Rule | Test Coverage | Status |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `ret_1d` | price_technical | INSTRUMENT | 2 | `daily_bars` | SPECIFIED | $kn < as\_of$, market_date < session | `test_compute::test_returns`, `test_engine::test_normal_path` | **VERIFIED** |
| 2 | `ret_5d` | price_technical | INSTRUMENT | 6 | `daily_bars` | SPECIFIED | $kn < as\_of$, market_date < session | `test_compute::test_returns`, `test_engine::test_low_confidence_bars_are_refused_never_used` | **VERIFIED** |
| 3 | `ret_20d` | price_technical | INSTRUMENT | 21 | `daily_bars` | SPECIFIED | $kn < as\_of$, market_date < session | `test_compute::test_returns`, `test_engine::test_known_bonus_is_adjusted` | **VERIFIED** |
| 4 | `sma_20` | price_technical | INSTRUMENT | 20 | `daily_bars` | n=20 | $kn < as\_of$, market_date < session | `test_compute::test_sma_and_distance`, `test_engine::test_known_bonus_is_adjusted` | **VERIFIED** |
| 5 | `sma_50` | price_technical | INSTRUMENT | 50 | `daily_bars` | n=50 | $kn < as\_of$, market_date < session | `test_compute::test_sma_and_distance` | **VERIFIED** |
| 6 | `sma_200` | price_technical | INSTRUMENT | 200 | `daily_bars` | n=200 | $kn < as\_of$, market_date < session | `test_compute::test_sma_and_distance`, `test_engine::test_normal_path` | **VERIFIED** |
| 7 | `close_to_sma_20` | price_technical | INSTRUMENT | 20 | `daily_bars` | n=20 | $kn < as\_of$, market_date < session | `test_compute::test_sma_and_distance` | **VERIFIED** |
| 8 | `close_to_sma_50` | price_technical | INSTRUMENT | 50 | `daily_bars` | n=50 | $kn < as\_of$, market_date < session | `test_compute::test_sma_and_distance` | **VERIFIED** |
| 9 | `close_to_sma_200` | price_technical | INSTRUMENT | 200 | `daily_bars` | n=200 | $kn < as\_of$, market_date < session | `test_compute::test_sma_and_distance` | **VERIFIED** |
| 10 | `ema_12` | price_technical | INSTRUMENT | 12 | `daily_bars` | n=12 | $kn < as\_of$, market_date < session | `test_compute::test_ema_seeded_with_sma` | **VERIFIED** |
| 11 | `ema_26` | price_technical | INSTRUMENT | 26 | `daily_bars` | n=26 | $kn < as\_of$, market_date < session | `test_compute::test_ema_seeded_with_sma` | **VERIFIED** |
| 12 | `rsi_14` | price_technical | INSTRUMENT | 15 | `daily_bars` | n=14 | $kn < as\_of$, market_date < session | `test_compute::test_rsi_wilder` | **VERIFIED** |
| 13 | `macd_line` | price_technical | INSTRUMENT | 26 | `daily_bars` | fast=12, slow=26 | $kn < as\_of$, market_date < session | `test_compute::test_macd_of_a_linear_series` | **VERIFIED** |
| 14 | `macd_trigger` | price_technical | INSTRUMENT | 34 | `daily_bars` | f=12, s=26, tr=9 | $kn < as\_of$, market_date < session | `test_compute::test_macd_of_a_linear_series` | **VERIFIED** |
| 15 | `macd_histogram` | price_technical | INSTRUMENT | 34 | `daily_bars` | f=12, s=26, tr=9 | $kn < as\_of$, market_date < session | `test_compute::test_macd_of_a_linear_series` | **VERIFIED** |
| 16 | `atr_14` | price_technical | INSTRUMENT | 15 | `daily_bars` | n=14 | $kn < as\_of$, market_date < session | `test_compute::test_atr` | **VERIFIED** |
| 17 | `atr_pct_14` | price_technical | INSTRUMENT | 15 | `daily_bars` | n=14 | $kn < as\_of$, market_date < session | `test_compute::test_atr` | **VERIFIED** |
| 18 | `volatility_20` | price_technical | INSTRUMENT | 21 | `daily_bars` | n=20, ann=252 | $kn < as\_of$, market_date < session | `test_compute::test_realised_vol` | **VERIFIED** |
| 19 | `beta_60` | price_technical | INSTRUMENT | 61 | `daily_bars`, `nifty_bars` | n=60, bm=Nifty50 | $kn < as\_of$, common dates only | `test_compute::test_beta` | **VERIFIED** |
| 20 | `dist_high_20` | price_technical | INSTRUMENT | 20 | `daily_bars` | n=20 | $kn < as\_of$, market_date < session | `test_compute::test_range_and_breakout` | **VERIFIED** |
| 21 | `dist_low_20` | price_technical | INSTRUMENT | 20 | `daily_bars` | n=20 | $kn < as\_of$, market_date < session | `test_compute::test_range_and_breakout` | **VERIFIED** |
| 22 | `breakout_20` | price_technical | INSTRUMENT | 21 | `daily_bars` | n=20 | $kn < as\_of$, market_date < session | `test_compute::test_range_and_breakout` | **VERIFIED** |
| 23 | `breakdown_20` | price_technical | INSTRUMENT | 21 | `daily_bars` | n=20 | $kn < as\_of$, market_date < session | `test_compute::test_range_and_breakout` | **VERIFIED** |
| 24 | `avg_volume_20` | volume_liquidity | INSTRUMENT | 20 | `daily_bars` | n=20 | $kn < as\_of$, market_date < session | `test_compute::test_volume` | **VERIFIED** |
| 25 | `volume_spike_20` | volume_liquidity | INSTRUMENT | 21 | `daily_bars` | n=20 | $kn < as\_of$, market_date < session | `test_compute::test_volume` | **VERIFIED** |
| 26 | `turnover_20` | volume_liquidity | INSTRUMENT | 20 | `daily_bars` | n=20 | $kn < as\_of$, market_date < session | `test_compute::test_volume` | **VERIFIED** |
| 27 | `pe` | fundamental | INSTRUMENT | 0 | `key_ratios` | SPECIFIED | Latest snapshot $kn < as\_of$ | `test_compute::test_ratios`, `test_engine::test_normal_path` | **VERIFIED** |
| 28 | `pb` | fundamental | INSTRUMENT | 0 | `key_ratios` | SPECIFIED | Latest snapshot $kn < as\_of$ | `test_compute::test_ratios` | **VERIFIED** |
| 29 | `roe_pct` | fundamental | INSTRUMENT | 0 | `key_ratios` | SPECIFIED | Latest snapshot $kn < as\_of$ | `test_compute::test_ratios` | **VERIFIED** |
| 30 | `roce_pct` | fundamental | INSTRUMENT | 0 | `key_ratios` | SPECIFIED | Latest snapshot $kn < as\_of$ | `test_compute::test_ratios` | **VERIFIED** |
| 31 | `ev_ebitda` | fundamental | INSTRUMENT | 0 | `key_ratios` | SPECIFIED | Latest snapshot $kn < as\_of$ | `test_compute::test_ratios` | **VERIFIED** |
| 32 | `pe_to_sector` | fundamental | INSTRUMENT | 0 | `key_ratios` | SPECIFIED | Latest snapshot $kn < as\_of$ | `test_compute::test_ratios`, `test_engine::test_normal_path` | **VERIFIED** |
| 33 | `pb_to_sector` | fundamental | INSTRUMENT | 0 | `key_ratios` | SPECIFIED | Latest snapshot $kn < as\_of$ | `test_compute::test_ratios` | **VERIFIED** |
| 34 | `revenue_yoy` | fundamental | INSTRUMENT | 0 | `income_yearly` | SPECIFIED | Latest yearly $kn < as\_of$ | `test_compute::test_growth` | **VERIFIED** |
| 35 | `pat_yoy` | fundamental | INSTRUMENT | 0 | `income_yearly` | SPECIFIED | Latest yearly $kn < as\_of$ | `test_compute::test_growth` | **VERIFIED** |
| 36 | `eps_yoy` | fundamental | INSTRUMENT | 0 | `income_yearly` | SPECIFIED | Latest yearly $kn < as\_of$ | `test_compute::test_growth` | **VERIFIED** |
| 37 | `revenue_yoy_q` | fundamental | INSTRUMENT | 0 | `income_quarterly` | SPECIFIED | Latest quarterly $kn < as\_of$ | `test_compute::test_growth`, `test_engine::test_delayed_financial_statement` | **VERIFIED** |
| 38 | `pat_yoy_q` | fundamental | INSTRUMENT | 0 | `income_quarterly` | SPECIFIED | Latest quarterly $kn < as\_of$ | `test_compute::test_growth` | **VERIFIED** |
| 39 | `liabilities_to_assets` | fundamental | INSTRUMENT | 0 | `balance_sheet` | SPECIFIED | Latest balance sheet $kn < as\_of$ | `test_compute::test_liabilities_to_assets` | **VERIFIED** |
| 40 | `ca_days_since_any` | event | INSTRUMENT | 0 | `corporate_actions` | SPECIFIED | Events with ex_date $\le$ session, $kn < as\_of$ | `test_compute::test_ca_days` | **VERIFIED** |
| 41 | `ca_days_since_dividend` | event | INSTRUMENT | 0 | `corporate_actions` | SPECIFIED | Dividend ex_date $\le$ session, $kn < as\_of$ | `test_compute::test_ca_days` | **VERIFIED** |
| 42 | `ca_days_since_split` | event | INSTRUMENT | 0 | `corporate_actions` | SPECIFIED | Split ex_date $\le$ session, $kn < as\_of$ | `test_compute::test_ca_days` | **VERIFIED** |
| 43 | `ca_days_since_bonus` | event | INSTRUMENT | 0 | `corporate_actions` | SPECIFIED | Bonus ex_date $\le$ session, $kn < as\_of$ | `test_compute::test_ca_days` | **VERIFIED** |
| 44 | `ca_days_to_any` | event | INSTRUMENT | 0 | `corporate_actions` | SPECIFIED | Next ex_date > session, $kn < as\_of$ | `test_compute::test_ca_days` | **VERIFIED** |
| 45 | `ca_days_to_dividend` | event | INSTRUMENT | 0 | `corporate_actions` | SPECIFIED | Next dividend ex_date > session, $kn < as\_of$ | `test_compute::test_ca_days` | **VERIFIED** |
| 46 | `ca_days_to_split` | event | INSTRUMENT | 0 | `corporate_actions` | SPECIFIED | Next split ex_date > session, $kn < as\_of$ | `test_compute::test_ca_days` | **VERIFIED** |
| 47 | `ca_days_to_bonus` | event | INSTRUMENT | 0 | `corporate_actions` | SPECIFIED | Next bonus ex_date > session, $kn < as\_of$ | `test_compute::test_ca_days` | **VERIFIED** |
| 48 | `news_count_24h` | event | INSTRUMENT | 0 | `news` | SPECIFIED | Published in $[as\_of - 24h, as\_of)$ | `test_compute::test_news_window_is_half_open_before_as_of` | **VERIFIED** |
| 49 | `news_count_7d` | event | INSTRUMENT | 0 | `news` | SPECIFIED | Published in $[as\_of - 7d, as\_of)$ | `test_compute::test_news_window_is_half_open_before_as_of` | **VERIFIED** |
| 50 | `news_hours_since_last` | event | INSTRUMENT | 0 | `news` | SPECIFIED | Hours from latest publication to $as\_of$ | `test_compute::test_news_window_is_half_open_before_as_of` | **VERIFIED** |
| 51 | `index_ret_1d` | market_context | CONTEXT | 2 | `daily_bars` | SPECIFIED | NIFTY 50 / NIFTY BANK bar $kn < as\_of$ | `test_engine::test_previous_session_bar_missing_is_never_replaced_by_an_older_one` | **VERIFIED** |
| 52 | `index_ret_5d` | market_context | CONTEXT | 6 | `daily_bars` | SPECIFIED | NIFTY 50 / NIFTY BANK bar $kn < as\_of$ | `test_engine::test_normal_path` | **VERIFIED** |
| 53 | `index_close_to_sma_50` | market_context | CONTEXT | 50 | `daily_bars` | n=50 | NIFTY 50 / NIFTY BANK bar $kn < as\_of$ | `test_engine::test_normal_path` | **VERIFIED** |
| 54 | `india_vix_level` | market_context | CONTEXT | 1 | `daily_bars` | SPECIFIED | VIX last close $kn < as\_of$ | `test_engine::test_india_vix_previous_session_missing` | **VERIFIED** |
| 55 | `india_vix_change_5d` | market_context | CONTEXT | 6 | `daily_bars` | n=5 | VIX close minus 5-sessions ago close | `test_compute::test_vix_global_sector` | **VERIFIED** |
| 56 | `fii_net_cash_1d` | market_context | CONTEXT | 0 | `fii_dii` | SPECIFIED | Previous session FII cash flow | `test_compute::test_valid_previous_session_observation`, Phase 5 harness | **VERIFIED** |
| 57 | `fii_net_cash_5d` | market_context | CONTEXT | 0 | `fii_dii` | n=5 | 5-day FII cash flow ending previous session | `test_compute::test_five_day_window_ending_before_the_previous_session_is_missing` | **VERIFIED** |
| 58 | `dii_net_cash_1d` | market_context | CONTEXT | 0 | `fii_dii` | SPECIFIED | Previous session DII cash flow | `test_compute::test_valid_previous_session_observation`, Phase 5 harness | **VERIFIED** |
| 59 | `dii_net_cash_5d` | market_context | CONTEXT | 0 | `fii_dii` | n=5 | 5-day DII cash flow ending previous session | `test_compute::test_five_day_window_ending_before_the_previous_session_is_missing` | **VERIFIED** |
| 60 | `global_ret_1d` | market_context | CONTEXT | 0 | `global_bars` | SPECIFIED | Return between 2 latest CONFIRMED labels | `test_compute::test_vix_global_sector` | **VERIFIED** |
| 61 | `sector_rs_20` | market_context | INSTRUMENT | 21 | `daily_bars`, `sector` | n=20, min_m=3 | PIT sector via `pit.sector(key, as_of)` | `test_compute::test_vix_global_sector` | **VERIFIED** |
| 62 | `preopen_gap_pct` | preopen | INSTRUMENT | 1 | `preopen`, `daily_bars` | SPECIFIED | IEP / previous close - 1 | `test_compute::test_values`, `test_engine::test_preopen_only_at_pre_open` | **VERIFIED** |
| 63 | `preopen_imbalance` | preopen | INSTRUMENT | 0 | `preopen` | SPECIFIED | (buy_qty - sell_qty) / (buy_qty + sell_qty) | `test_compute::test_values` | **VERIFIED** |
| 64 | `preopen_ieq` | preopen | INSTRUMENT | 0 | `preopen` | SPECIFIED | Indicative equilibrium quantity | `test_compute::test_values` | **VERIFIED** |
| 65 | `preopen_ieq_to_avg_volume` | preopen | INSTRUMENT | 20 | `preopen`, `daily_bars` | n=20 | ieq / avg_volume_20 | `test_compute::test_values` | **VERIFIED** |

*Complete machine-readable generated audit matrix:* [`audit/evidence/STAGE_3_FEATURE_AUDIT_GENERATED.md`](file:///home/cis/windows/prajna/audit/evidence/STAGE_3_FEATURE_AUDIT_GENERATED.md).

---

## 16. Acceptance Gate Verification

### Audit Method
Executed `prajna acceptance stage3 --run-tests` to capture criteria A through O and readiness levels.

### Results
- **Command:** `.venv/bin/prajna acceptance stage3 --run-tests --out /home/cis/windows/prajna/audit/evidence/stage3_run.json --md /home/cis/windows/prajna/audit/evidence/STAGE_3_ACCEPTANCE_RUN.md`
- **Exit Code:** `1` (by design: overall is `NOT COMPLETE` until production evidence exists)
- **JSON Evidence:** [`audit/evidence/stage3_run.json`](file:///home/cis/windows/prajna/audit/evidence/stage3_run.json)
- **Document Evidence:** [`audit/evidence/STAGE_3_ACCEPTANCE_RUN.md`](file:///home/cis/windows/prajna/audit/evidence/STAGE_3_ACCEPTANCE_RUN.md)

### Detailed Criteria Status
- **A (Registry coverage):** **PASS** (65 features, 31 diagram items mapped).
- **B (Determinism):** **PASS** (recomputed probe sample identical in values, reasons, and SHA-256 hashes).
- **C (Point in time):** **PASS** (0 dry-run violations, 0 stored violations; $knowable\_at < as\_of$).
- **D (Look-ahead probe):** **PASS** (past snapshot 2026-09-18 uses 0 bars of its session or later).
- **E (Corporate actions):** **PASS** (302 adjusted bars in sample; LOW-confidence refused).
- **F (Missing data):** **PASS** (values XOR reason code strictly satisfied; 0 contract violations).
- **G (Idempotency):** **PASS** (0 duplicate keys stored; `uq_feature_value` enforced; tests pass).
- **H (Execution lock):** **PASS** (`locks.require` in engine verified; write token failure verified).
- **I (Backfill lock):** **PASS** (`PRAJNA_STAGE3_BACKFILL_ENABLED` required).
- **J (No vendor call):** **PASS** (0 vendor imports in `app.features`).
- **K (Full test suite):** **PASS** (1,104 passed, 2 skipped in 340.08s).
- **L (Dry-run real data):** **PASS** (sample of 20 instruments computed at both snapshots with 0 errors).
- **M (Prerequisites):** **PASS** (Stage 1 evaluated live as `COMPLETE`; Stage 2 verified `PASS`).
- **N (Decisions approved):** **PASS** (All 5 Stage 3 decisions approved).
- **O (Production evidence):** **PENDING** (0 complete runs, 0 stored values in production database).

### Readiness Levels
- `IMPLEMENTED`: **YES** (65 features, 31 diagram items)
- `TESTED`: **YES** (Criterion K PASS, 1,104 tests passing)
- `DRY-RUN READY`: **YES** (Criteria A–L PASS)
- `PRODUCTION READY`: **YES** (Criteria M PASS, N PASS)
- `PRODUCTION UNLOCKED`: **no** (`PRAJNA_STAGE3_ENABLED=false`, kill switch off)
- `BACKFILL EXECUTED`: **no** (0 committed backfill runs; backfill deferred)

---

## 17. News Separation Verification

### Audit Findings
- **Registry Separation:** Multi-source news features (`mnews_*`) reside in [`app/features/news_features.py`](file:///home/cis/windows/prajna/backend/app/features/news_features.py). They are NOT registered in `app/features/registry.py` (`features-v1`).
- **Decision Status:** Decision `FEATURE-NEWS-V2` is explicitly `PENDING` (tested in `backend/tests/news/test_news_features.py:79`).
- **Gate Separation:** News acceptance is verified independently via `prajna acceptance news`.
- **Zero Leakage:** No `mnews_*` values exist in `feature_value` or Stage 3 production schemas.

---

## 18. Safety Verification

Every production safety lock was verified:

- [x] `PRAJNA_STAGE3_ENABLED = false` (absent from `backend/.env`, default in code is `False`).
- [x] `PRAJNA_STAGE3_BACKFILL_ENABLED = false` (absent from `backend/.env`, default in code is `False`).
- [x] `PRAJNA_NEWS_MULTI_SOURCE_ENABLED = false` (absent from `backend/.env`, default in code is `False`).
- [x] Kill switch file (`backend/var/run/stage3.kill`): Absent.
- [x] Write token: Not supplied to any command; never hardcoded in scripts.
- [x] System crontab: Contains 0 Stage 3 entries.
- [x] Systemd: Contains 0 Stage 3 services or timers.
- [x] Stage 3 production feature rows: **0**.
- [x] Stage 3 production runs: **0**.
- [x] Production modifications during audit: **0**.

---

## 19. Findings & Discovered Bugs

### BUG ID: `BUG-STAGE3-PERSIST-PARAM-LIMIT`
- **Location:** [`backend/app/features/engine.py:330-333`](file:///home/cis/windows/prajna/backend/app/features/engine.py#L330-L333)
- **Reproduction:**
  ```python
  inserted, _ = await E.persist(s, res, run_id)
  ```
  Where `res` contains feature rows for the active universe of 3,547 instruments ($\approx 180,919$ rows).
- **Expected Behavior:** `persist()` batches rows into parameter sets that never exceed PostgreSQL/`asyncpg` limits ($\le 32,767$ parameters per query).
- **Actual Behavior:**  
  The loop chunks rows by 5,000:
  ```python
  for i in range(0, len(values), 5000):
      chunk = values[i:i + 5000]
      inserted += (await s.execute(pg_insert(FeatureValue).values(chunk).on_conflict_do_nothing(
          constraint="uq_feature_value"))).rowcount
  ```
  Because `FeatureValue` has 15 columns, 5,000 rows require $5,000 \times 15 = 75,000$ bind parameters. `asyncpg` raises:
  `asyncpg.exceptions._base.InterfaceError: the number of query arguments cannot exceed 32767`.
  Every full-universe production commit crashes and rolls back.
- **Severity:** **CRITICAL / PRODUCTION BLOCKER**
- **Recommended Fix (DO NOT IMPLEMENT NOW):**  
  Reduce batch chunk size to $\le 2,000$ rows (e.g. 1,000 or 2,000 rows):
  ```python
  for i in range(0, len(values), 2000):  # 2,000 * 15 = 30,000 <= 32,767
  ```

---

### BUG ID: `BUG-STAGE1-CLI-CWD-RELATIVE-PATHS`
- **Location:** [`backend/app/acceptance/stage1.py:344, 518, 611`](file:///home/cis/windows/prajna/backend/app/acceptance/stage1.py#L344)
- **Reproduction:** Execute `prajna acceptance stage1` from `/home/cis/windows/prajna` instead of `/home/cis/windows/prajna/backend`.
- **Expected Behavior:** Criterion K, R, and X find their respective artifact files in `backend/var/` regardless of invocation Cwd.
- **Actual Behavior:** Hardcoded relative paths `pathlib.Path("var/acceptance")` and `pathlib.Path("var/logs/daily")` resolve to the parent directory where `var/` does not exist, causing K to FAIL, R to wait, and X to wait (`OVERALL: NOT COMPLETE`).
- **Severity:** **MEDIUM / OPERATIONAL DEFECT**
- **Recommended Fix (DO NOT IMPLEMENT NOW):** Anchor paths to `pathlib.Path(__file__).resolve().parents[2] / "var"`.

---

### GAP ID: `DOC-GAP-SCHEDULE`
- **Location:** [`backend/ops/cron/prajna.cron:51`](file:///home/cis/windows/prajna/backend/ops/cron/prajna.cron#L51)
- **Description:** Line 51 references `docs/STAGE_3_PRODUCTION_SCHEDULE.md`, but the file does not exist on disk. Decision `SCHEDULE` is `PENDING_APPROVAL`.
- **Severity:** **LOW / DOCUMENTATION GAP**
- **Recommended Fix:** Author `docs/STAGE_3_PRODUCTION_SCHEDULE.md` documenting the Option A vs Option B trade-off for pre-open capture before production unlock.

---

## 20. Final Readiness Determination

### Final Status Determination

```
========================================================================================
FINAL AUDIT VERDICT:
NOT PRODUCTION READY — FAILURES FOUND
========================================================================================
```

### Justification
1. While Stage 1 is verified COMPLETE, Stage 2 is verified PASS, and Stage 3 mathematical indicators are verified DRY-RUN READY with all 5 decisions approved, **Stage 3 cannot legitimately reach PRODUCTION READY until the critical batch persistence parameter overflow (`BUG-STAGE3-PERSIST-PARAM-LIMIT`) is resolved**.
2. If an operator were to unlock production today and trigger `prajna stage3 run --commit`, the run would fail on the database insert with `InterfaceError: the number of query arguments cannot exceed 32767`.
3. In strict accordance with the audit mandate ("NO ASSUMPTIONS. If evidence contradicts the claim: mark it FAILED"), a system whose production persistence path deterministically crashes cannot be certified as Production Ready.

---

## Audit Metadata & Traceability

### Exact Commands Executed
- `git status`
- `git rev-parse HEAD && git log -n 15 --oneline`
- `backend/.venv/bin/prajna acceptance stage1 --out audit/evidence/stage1_run.json --md audit/evidence/STAGE_1_FINAL_ACCEPTANCE_RUN.md` (Cwd: `/home/cis/windows/prajna`)
- `.venv/bin/prajna acceptance stage1 --out /home/cis/windows/prajna/audit/evidence/stage1_run_backend_cwd.json --md /home/cis/windows/prajna/audit/evidence/STAGE_1_ACCEPTANCE_FROM_BACKEND.md` (Cwd: `backend/`)
- `.venv/bin/prajna acceptance stage2 --run-tests --out /home/cis/windows/prajna/audit/evidence/stage2_run.json --md /home/cis/windows/prajna/audit/evidence/STAGE_2_ACCEPTANCE_RUN.md`
- `.venv/bin/prajna acceptance stage3 --run-tests --out /home/cis/windows/prajna/audit/evidence/stage3_run.json --md /home/cis/windows/prajna/audit/evidence/STAGE_3_ACCEPTANCE_RUN.md`
- `.venv/bin/python -m app.features.audit_doc > /home/cis/windows/prajna/audit/evidence/STAGE_3_FEATURE_AUDIT_GENERATED.md`
- `.venv/bin/pytest -s -v tests/stage3/test_engine.py::TestSnapshotConsistency`
- `.venv/bin/pytest -s -v tests/stage3/test_engine.py::TestAdversarialPointInTime tests/stage3/test_engine.py::TestRun tests/stage3/test_engine.py::TestLocks`
- `.venv/bin/python ops/measure/stage3_timing.py --session 2026-09-28 --snapshot PRE_SESSION`
- Pure compute runtime measurement script on 3,547 instruments.

### Test Execution Counts
- Full Regression Test Suite (`stage2 --run-tests` & `stage3 --run-tests`): **1,104 passed, 2 skipped** (Duration: 330.11s & 340.08s).
- Stage 3 Targeted PIT, Atomicity, and Lock Suites: **25 passed, 0 failed**.
- FII/DII Staleness Custom Harness: **9 passed, 0 failed**.

### Files Inspected
- `backend/app/features/registry.py`
- `backend/app/features/engine.py`
- `backend/app/features/inputs.py`
- `backend/app/features/locks.py`
- `backend/app/features/decisions.py`
- `backend/app/features/news_features.py`
- `backend/app/features/audit_doc.py`
- `backend/app/features/compute/context.py`
- `backend/app/acceptance/stage1.py`
- `backend/app/acceptance/stage2.py`
- `backend/app/acceptance/stage3.py`
- `backend/ops/cron/prajna.cron`
- `backend/ops/runbooks/stage3_snapshot.sh`
- `backend/ops/measure/stage3_timing.py`
- `backend/tests/stage3/test_compute.py`
- `backend/tests/stage3/test_engine.py`
- `backend/app/db/migrations/versions/0011_stage3_features.py`
- `docs/STAGE_1_FINAL_ACCEPTANCE.md`
- `docs/STAGE_2_ACCEPTANCE.md`
- `docs/STAGE_3_ACCEPTANCE.md`
- `docs/STAGE_3_READY_FOR_UNLOCK.md`

### Production Commands NOT Executed
- `prajna stage3 run --commit` (NOT run with token)
- `prajna stage3 backfill --commit` (NOT run with token)
- Cron installation (`crontab ops/cron/prajna.cron`) (NOT run)
- Systemd installation / modification (NOT run)
- Production lock modification / token export (NOT run)

### Modifications Made
- **Zero changes made to existing production code, migrations, configs, or test files.**
- Files created:
  - `docs/STAGE_3_INDEPENDENT_AUDIT.md` (this report)
  - `audit/evidence/*` (12 raw audit and machine-readable evidence files)

### Blockers Before Production Readiness
1. Fix batch chunking in `app/features/engine.py:330` from 5,000 to 2,000 rows.
2. Fix relative path anchors in `app/acceptance/stage1.py`.
3. Author `docs/STAGE_3_PRODUCTION_SCHEDULE.md` and approve decision `SCHEDULE` (resolving pre-open replay timing).

### Recommended Next Action
Once explicitly instructed by the user, apply the 1-line batch size fix in `backend/app/features/engine.py:330` (`values[i:i + 2000]`), rerun `stage3_timing.py` to confirm full persistence into the test database, and author the schedule documentation.
