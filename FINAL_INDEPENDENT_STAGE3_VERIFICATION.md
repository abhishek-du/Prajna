# Final Independent Forensic Verification Report: Stage 3

**Document:** `FINAL_INDEPENDENT_STAGE3_VERIFICATION.md`  
**Execution Date:** 2026-09-28T21:45:00+05:30  
**Auditor:** Independent Auditor & Verification Engineer  
**Audit Standard:** Strict Empirical Verification — Read-Only, Zero Code Changes, Evidence-First  
**Repository:** `/home/cis/windows/prajna`  
**HEAD Commit:** `975d6b3ca2edbcc20da02eed6cc92fa3f0c0e15a`  
**Machine-Readable Deliverable:** [`FINAL_INDEPENDENT_STAGE3_VERIFICATION.json`](file:///home/cis/windows/prajna/FINAL_INDEPENDENT_STAGE3_VERIFICATION.json)

---

## 1. CURRENT HEAD

- **CLAIM:** Current repository HEAD commit is `975d6b3ca2edbcc20da02eed6cc92fa3f0c0e15a`.
- **METHOD:** Executed `git rev-parse HEAD` and `git log -1 --format="%H %s"`.
- **EVIDENCE:**
  ```text
  975d6b3ca2edbcc20da02eed6cc92fa3f0c0e15a stage3: record schedule approval (PRE_OPEN option B), not installed
  ```
- **RESULT:** **VERIFIED**

---

## 2. GIT STATE

- **CLAIM:** Working tree is clean of code and database modifications, matching main branch HEAD.
- **METHOD:** Executed `git status`.
- **EVIDENCE:**
  - Branch: `main`
  - Upstream: synchronized
  - Unstaged tracked changes: Exactly 1 file modified dynamically by the running background dry-run collector (`docs/NEWS_MULTI_SOURCE_ACCEPTANCE.md`).
  - Untracked files: Only audit evidence reports, scratch files, and documentation deliverables.
  - Zero modifications to application source code, migrations, configs, or test files.
- **RESULT:** **VERIFIED**

---

## 3. PRODUCTION SAFETY STATE

- **CLAIM:** Production execution remains strictly locked, disabled, and unexecuted.
- **METHOD:** Inspected runtime settings, environment variables, filesystem locks, and database tables.
- **EVIDENCE:**
  1. `PRAJNA_STAGE3_ENABLED = False` (verified via `app.core.config.get_settings()`; default in code is `False`, absent from `.env`).
  2. `PRAJNA_STAGE3_BACKFILL_ENABLED = False` (default in code is `False`, absent from `.env`).
  3. No production write token supplied (`PRAJNA_SUPPLIED_TOKEN` not exported in shell).
  4. Kill switch file (`backend/var/run/stage3.kill`): Absent.
  5. `feature_value` table in production database `prajna`: **0 rows**.
  6. `ingest_run` rows with `stream LIKE 'features%'`: **0 rows**.
  7. Successful production runs: **0**.
  8. Backfill execution: **0 rows**.
- **RESULT:** **VERIFIED**

---

## 4. SCHEDULE APPROVAL

- **CLAIM:** Decision `SCHEDULE` is approved with PRE_OPEN Option B, and Option A is not prepared.
- **METHOD:** Inspected `docs/STAGE_3_PRODUCTION_SCHEDULE.md`, `docs/STAGE_3_DECISIONS.md`, `backend/ops/cron/prajna.cron`, and git commit `975d6b3`.
- **EVIDENCE:**
  - In [`docs/STAGE_3_PRODUCTION_SCHEDULE.md:3`](file:///home/cis/windows/prajna/docs/STAGE_3_PRODUCTION_SCHEDULE.md#L3):
    > *Decision SCHEDULE: APPROVED by the user on 2026-09-28, with PRE_OPEN option B ("Approve schedule with PRE_OPEN option B").*
  - **PRE_SESSION Snapshot:** `as_of = 08:59:59 IST`, start = `09:00:30 IST` (Mon–Fri).
  - **PRE_OPEN Snapshot:** `as_of = 09:08:00 IST`, start = `09:22:00 IST` (Mon–Fri; 09:21 is reserved for `timing_monitor.sh`), waits for `preopen_day.sh` tick replay (`--after-replay`).
  - Option A (09:08:30 with missing inputs): Explicitly documented as NOT chosen and omitted from cron.
  - Cron lines in `backend/ops/cron/prajna.cron` are prefixed `# APPROVED_NOT_INSTALLED:`.
- **RESULT:** **VERIFIED**

---

## 5. CRON INSTALLATION STATE

- **CLAIM:** Zero active Stage 3 jobs exist in crontab or systemd.
- **METHOD:** Inspected `crontab -l`, `systemctl --user list-timers`, and `systemctl --user list-units`.
- **EVIDENCE:**
  - `crontab -l | grep stage3`: **0 matches** (exit code 1).
  - In `backend/ops/cron/prajna.cron`: Lines 57 and 61 remain commented:
    ```cron
    # APPROVED_NOT_INSTALLED: 0 9 * * 1-5   cd $B && sleep 30 && ops/runbooks/stage3_snapshot.sh PRE_SESSION --token-from-dotenv >> var/logs/cron.log 2>&1
    # APPROVED_NOT_INSTALLED: 22 9 * * 1-5  cd $B && ops/runbooks/stage3_snapshot.sh PRE_OPEN --after-replay --token-from-dotenv >> var/logs/cron.log 2>&1
    ```
  - Systemd user units: 0 loaded or active units for `prajna` or `stage3`.
- **RESULT:** **VERIFIED**

---

## 6. RUNBOOK SAFETY

- **CLAIM:** [`backend/ops/runbooks/stage3_snapshot.sh`](file:///home/cis/windows/prajna/backend/ops/runbooks/stage3_snapshot.sh) strictly enforces locks, replay dependencies, token isolation, and idempotency.
- **METHOD:** Forensic source code analysis of `stage3_snapshot.sh`.
- **EVIDENCE:**
  1. `flock`: Line 70–75 acquires `var/run/stage3.lock` (`flock -w 300`).
  2. Engine lock enforcement: Invokes `.venv/bin/python -m app.cli.main --plain stage3 run --session "$TODAY" --snapshot "$KIND" --commit`. There is no bypass parameter.
  3. Pre-open replay wait: Lines 54–68 poll `var/logs/preopen_${TODAY}.log` for `"replay exit 0"`. Timeout or failure exits 1 with `STAGE3_SKIP` and writes nothing.
  4. Token handling: Lines 49–51 export `PRAJNA_SUPPLIED_TOKEN` only in the environment. It is never passed as a command argument or printed in logs.
  5. Lateness marking: Lines 96–98 tag runs completed after 09:15 IST as `STAGE3_LATE` while preserving point-in-time `as_of`.
  6. Idempotency: Duplicate runs find all existing rows via `on_conflict_do_nothing` and report `inserted=0`.
- **RESULT:** **VERIFIED**

---

## 7. PERSISTENCE VERIFICATION

- **CLAIM:** Batch insert parameter overflow (`BUG-STAGE3-PERSIST-PARAM-LIMIT`) is fixed, bounding statements to $\le 30,000$ bind parameters.
- **METHOD:** Inspected `backend/app/features/engine.py` and executed `backend/tests/stage3/test_engine.py::TestPersistScale`.
- **EVIDENCE:**
  - In [`backend/app/features/engine.py:60-66`](file:///home/cis/windows/prajna/backend/app/features/engine.py#L60-L66):
    ```python
    ASYNCPG_MAX_BIND_PARAMS = 32767
    PARAM_BUDGET = 30000

    def batch_rows(params_per_row: int) -> int:
        return max(1, PARAM_BUDGET // max(1, params_per_row))
    ```
  - For `FeatureValue` with 15 bind parameters per row:
    $\text{batch\_rows}(15) = 30,000 // 15 = 2,000 \text{ rows}$.
    $2,000 \times 15 = 30,000 \le 32,767$.
  - In [`backend/app/features/engine.py:341-343`](file:///home/cis/windows/prajna/backend/app/features/engine.py#L341-L343):
    ```python
    step = batch_rows(len(values[0])) if values else 1
    for i in range(0, len(values), step):
        chunk = values[i:i + step]
    ```
  - Executed tests in `TestPersistScale`:
    - `test_bind_parameters_per_row_are_counted_from_the_real_statement`: **PASS**
    - `test_rows_across_several_batches_persist_then_rerun_is_idempotent`: **PASS** (5,000 rows batched across 3 statements of 30,000 / 30,000 / 15,000 parameters)
    - `test_a_failure_after_a_batch_leaves_no_partial_snapshot`: **PASS**
- **RESULT:** **VERIFIED**

---

## 8. FULL-UNIVERSE VERIFICATION

- **CLAIM:** Full-universe computation and persistence measurements (180,919 PRE_SESSION rows, 195,107 PRE_OPEN rows across 3,547 instruments) were executed with real production data into an isolated test schema with zero production writes.
- **METHOD:** Inspected `backend/ops/measure/stage3_persistence_verify.py`, `audit/evidence/STAGE_3_PERSISTENCE_VERIFICATION.md`, and `audit/evidence/stage3_persistence_full_universe.json`.
- **EVIDENCE:**
  - Computation: Computed directly from production database `prajna` (READ ONLY, REPEATABLE READ) in 140.3s (PRE_SESSION) and 156.1s (PRE_OPEN).
  - Persistence: Persisted into an isolated schema `stage3_verify_2396614` in database `prajna_test` with identical DDL, indexes, and triggers, executing real COMMITs in 72.6s (PRE_SESSION) and 76.8s (PRE_OPEN).
  - Schema was cleanly dropped after verification.
  - Production database `prajna` had 0 rows before and 0 rows after.
  - Classification: **TEST SCHEMA EXECUTION on REAL MARKET DATA**.
- **RESULT:** **VERIFIED**

---

## 9. POINT-IN-TIME (PIT) VERIFICATION

- **CLAIM:** Indicator inputs strictly enforce $knowable\_at < as\_of$; revisions, corporate actions, and financial statement delays are point-in-time safe.
- **METHOD:** Executed `pytest -v tests/stage3/test_engine.py::TestPointInTime tests/stage3/test_engine.py::TestAdversarialPointInTime`.
- **EVIDENCE:**
  - Late bar revision invisible: **PASS** (`test_late_bar_revision_invisible`)
  - Late previous-session bar: **PASS** (`test_previous_session_bar_missing_is_never_replaced_by_an_older_one`)
  - Microsecond boundary: **PASS** (`test_knowable_boundary_one_microsecond`)
  - Corporate action revised after `as_of`: **PASS** (`test_corporate_action_revised_after_as_of`)
  - Delayed financial statement: **PASS** (`test_financial_statement_delayed`)
  - India VIX missing previous session: **PASS** (`test_india_vix_missing_previous_session`)
  - FII/DII published after `as_of`: **PASS** (`test_fii_dii_published_after_as_of_is_invisible`)
  - Stale FII/DII: **PASS** (`test_older_observation_is_not_relabelled_as_current`)
  - Holiday boundary FII/DII: **PASS** (`test_holiday_boundary_uses_previous_trading_session`)
- **RESULT:** **VERIFIED**

---

## 10. REPEATABLE READ SNAPSHOT ISOLATION

- **CLAIM:** Stage 3 run transactions require `REPEATABLE READ` isolation, preventing mid-run concurrent canon commits from leaking into a snapshot.
- **METHOD:** Inspected `app/features/engine.py:consistent_read()` and executed `tests/stage3/test_engine.py::TestSnapshotConsistency`.
- **EVIDENCE:**
  - In [`backend/app/features/engine.py:101-118`](file:///home/cis/windows/prajna/backend/app/features/engine.py#L101-L118):
    ```python
    iso = (await s.execute(text("show transaction isolation level"))).scalar().upper()
    if iso not in ("REPEATABLE READ", "SERIALIZABLE"):
        raise SnapshotIsolationError(...)
    ```
  - Executed `test_concurrent_commit_is_invisible_to_running_snapshot`: A concurrent transaction modified canonical data and committed while Stage 3 was reading; Stage 3 saw only the initial snapshot state.
  - Executed `test_read_committed_is_refused`: Non-repeatable transactions are refused.
- **RESULT:** **VERIFIED**

---

## 11. ATOMICITY

- **CLAIM:** A snapshot run is atomic; an error mid-run leaves zero feature rows and records a failed run.
- **METHOD:** Inspected `app/features/engine.py:run_snapshot()` and executed `tests/stage3/test_engine.py::test_a_failure_after_a_batch_leaves_no_partial_snapshot`.
- **EVIDENCE:**
  - Injected error after the first batch of 2,000 rows: All inserted rows rolled back.
  - Verification query: `SELECT count(*) FROM feature_value` returned `0`.
  - Ingest run status transitioned to `FAILED`.
- **RESULT:** **VERIFIED**

---

## 12. IDEMPOTENCY

- **CLAIM:** Recomputing an existing snapshot produces identical values and inserts 0 new rows without duplicates.
- **METHOD:** Inspected unique constraint `uq_feature_value` and executed `tests/stage3/test_engine.py::test_run_writes_then_rerun_is_idempotent`.
- **EVIDENCE:**
  - Second execution reported: `inserted=0`, `already_present=rows`.
  - Database row count remained identical.
  - Zero duplicate keys across `(instrument_key, session_date, snapshot, feature_id, feature_version)`.
- **RESULT:** **VERIFIED**

---

## 13. DETERMINISM

- **CLAIM:** Recomputed features with modified inputs are detected as determinism mismatches and refuse to overwrite existing data.
- **METHOD:** Executed `tests/stage3/test_engine.py::test_determinism_mismatch_never_overwrites`.
- **EVIDENCE:**
  - Backdated fact injected to alter P/E calculation from 20.0 to 30.0.
  - Execution aborted with `DeterminismMismatch`.
  - Stored value in `feature_value` remained unchanged at 20.0.
  - Run failed and transaction rolled back.
- **RESULT:** **VERIFIED**

---

## 14. LOCKS

- **CLAIM:** Engine-level locks refuse unauthorized execution independently of CLI options.
- **METHOD:** Inspected `app/features/locks.py` and executed `tests/stage3/test_engine.py::TestLocks`.
- **EVIDENCE:**
  - `PRAJNA_STAGE3_ENABLED=false`: REFUSED (`stage3_enabled`).
  - Kill switch engaged: REFUSED (`kill_switch_off`).
  - Stage 1 not complete: REFUSED (`stage1_complete`).
  - Stage 2 failed: REFUSED (`stage2_pass`).
  - Decisions pending: REFUSED (`decisions_approved`).
  - Missing/invalid write token: REFUSED (`write_token`).
  - Backfill flag missing: REFUSED (`backfill_enabled`).
  - Every refusal writes a `REFUSED` record to `stage3_event` and aborts without writing features.
- **RESULT:** **VERIFIED**

---

## 15. STAGE 1 CWD FIX

- **CLAIM:** Commit `69a3a94` removes working-directory sensitivity from Stage 1 acceptance by anchoring paths to `BACKEND_ROOT`.
- **METHOD:** Executed `prajna acceptance stage1` from `/home/cis/windows/prajna` (repo root) and `/home/cis/windows/prajna/backend`, and executed `tests/unit/test_acceptance_stage1_cwd.py`.
- **EVIDENCE:**
  - Run from repository root: Exit code 0, 21 PASS, 4 DEFERRED, 2 OUT_OF_SCOPE, **`OVERALL: COMPLETE`**.
  - Run from `backend/`: Exit code 0, 21 PASS, 4 DEFERRED, 2 OUT_OF_SCOPE, **`OVERALL: COMPLETE`**.
  - All 5 unit tests in `test_acceptance_stage1_cwd.py` passed in 0.63s.
- **RESULT:** **VERIFIED**

---

## 16. NEWS SEPARATION

- **CLAIM:** Multi-source news (`mnews_*`) remains strictly segregated from Stage 3; `FEATURE-NEWS-V2` is `PENDING`, and production tables contain 0 rows.
- **METHOD:** Inspected `app/features/registry.py`, `app/features/news_features.py`, and production database counts.
- **EVIDENCE:**
  - Stage 3 Registry: Exactly 65 features under `features-v1`; exactly 0 `mnews_*` features registered.
  - Registered news features: Exactly 3 (`news_count_24h`, `news_count_7d`, `news_hours_since_last`).
  - Decision `FEATURE-NEWS-V2`: Explicitly `PENDING`.
  - Multi-source production tables (`news_item`, `news_story`, `news_assessment`, `news_poll`): Exactly **0 rows**.
  - Production write flags (`PRAJNA_NEWS_*_ENABLED`): All **`False`**.
- **RESULT:** **VERIFIED**

---

## 17. ACCEPTANCE TEST RESULTS

- **CLAIM:** The test suites and acceptance gates execute cleanly.
- **METHOD:** Executed `pytest` on Stage 3, Stage 1 acceptance, Stage 2 acceptance, and Stage 3 acceptance.
- **EVIDENCE:**
  - **Stage 3 Unit & Integration Tests:** **100 passed in 94.24s** (0 failed, 0 skipped).
  - **Stage 1 Acceptance:** Exit code 0, **`OVERALL: COMPLETE`**.
  - **Stage 2 Acceptance:** Criteria A–K, M–O **PASS**; L and P PENDING (without `--run-tests`). (All 16 PASS when run with `--run-tests`).
  - **Stage 3 Acceptance:** Criteria A–F, H–J, L–N **PASS**; G and K NOT_RUN (without `--run-tests`); O **PENDING** (production evidence). Level reached: **`PRODUCTION READY`**. Level not reached: `PRODUCTION UNLOCKED` (by design).
- **RESULT:** **VERIFIED**

---

## 18. PRODUCTION DATABASE STATE

- **CLAIM:** Production database `prajna` contains zero Stage 3 feature records, zero Stage 3 ingest runs, and zero multi-source news items.
- **METHOD:** Executed read-only SQL queries against database `prajna`.
- **EVIDENCE:**
  - `SELECT count(*) FROM feature_value`: **`0`**
  - `SELECT count(*) FROM ingest_run WHERE stream LIKE 'features%'`: **`0`**
  - `SELECT count(*) FROM stage3_event`: **`4`** (All 4 are historical `REFUSED` events)
  - `SELECT count(*) FROM news_item`: **`0`**
  - `SELECT count(*) FROM news_story`: **`0`**
  - `SELECT count(*) FROM news_assessment`: **`0`**
  - Legacy Upstox `news_article`: 197 rows (18 from today)
- **RESULT:** **VERIFIED**

---

## 19. SEARCH FOR HIDDEN EXECUTION

- **CLAIM:** No production executions or backfill attempts have occurred after the previous audit.
- **METHOD:** Searched database tables, systemd timers, crontab, process lists, and daily logs.
- **EVIDENCE:**
  - Daily log directory `backend/var/logs/daily/*stage3*`: 0 files found.
  - `cron.log`: 0 Stage 3 entries found.
  - `stage3_event`: Max ID is 4, timestamp `2026-09-28 09:30:18 UTC`. Zero events recorded during or after the fix commits.
  - Active OS processes: Zero processes executing `stage3 run` or `stage3 backfill`.
- **RESULT:** **VERIFIED**

---

## 20. NEW FINDINGS

During this forensic audit, two operational/testing discrepancies were uncovered:

### Finding 1: Unanchored Default Paths in Stage 2 & Stage 3 CLI
- **ID:** `BUG-CLI-STAGE2-STAGE3-DEFAULT-PATHS-UNANCHORED`
- **Severity:** **LOW / OPERATIONAL DEFECT**
- **Location:** [`backend/app/cli/main.py:1313-1314`](file:///home/cis/windows/prajna/backend/app/cli/main.py#L1313-L1314) & [`backend/app/cli/main.py:1561-1562`](file:///home/cis/windows/prajna/backend/app/cli/main.py#L1561-L1562)
- **Mechanism:**
  While `acceptance_stage1` was updated in commit `69a3a94` to anchor default output paths using `anchored()`, `acceptance_stage2` and `acceptance_stage3` still use unanchored relative defaults:
  - `out: str = typer.Option("var/acceptance/stage2.json", "--out")`
  - `md: str = typer.Option("../docs/STAGE_2_ACCEPTANCE.md", "--md")`
  - `out: str = typer.Option("var/acceptance/stage3.json", "--out")`
  - `md: str = typer.Option("../docs/STAGE_3_ACCEPTANCE.md", "--md")`
- **Impact:** Running `prajna acceptance stage2` or `stage3` from repository root `/home/cis/windows/prajna` without explicit `--out` and `--md` will write `var/acceptance/` in the repository root or attempt to write markdown into `/home/cis/windows/docs/` (outside the repository). They must be invoked from `backend/` or provided explicit absolute paths.
- **Recommended Remediation (DO NOT FIX NOW):** Mirror the fix from `acceptance_stage1` by defaulting to `None` and resolving paths via `anchored()`.

### Finding 2: Installed Crontab Assertion Drift in Live Test
- **ID:** `TEST-CRONTAB-DRIFT-ASSERTION`
- **Severity:** **INFORMATIONAL**
- **Location:** [`backend/tests/live/test_installed_cron.py:23`](file:///home/cis/windows/prajna/backend/tests/live/test_installed_cron.py#L23)
- **Mechanism:**
  The test asserts character-for-character equality: `assert installed == REPO.read_text()`.
  Because `backend/ops/cron/prajna.cron` was updated in commit `975d6b3` to include the commented `# APPROVED_NOT_INSTALLED:` Stage 3 lines, but `crontab ops/cron/prajna.cron` was intentionally NOT run, running `pytest -m live tests/live/test_installed_cron.py` fails on the string comparison.
- **Impact:** None on system safety. The safety test `test_installed_schedule_is_safe()` passes. This is the expected and correct state when keeping the crontab clean before unlock.

---

## 21. FINAL DETERMINATION

```text
========================================================================================
FINAL AUDIT VERDICT:
PRODUCTION READY — ALL CLAIMS VERIFIED

STATUS:
PRODUCTION READY   : YES
PRODUCTION UNLOCKED: NO
CRON INSTALLED     : NO
========================================================================================
```

### Forensic Summary

1. **All Blocker Bugs Are Resolved:**
   - `BUG-STAGE3-PERSIST-PARAM-LIMIT` is eliminated. Batch size is bounded to 2,000 rows ($\le 30,000$ bind parameters). Full-universe persistence on 3,547 instruments (180,919 PRE_SESSION rows and 195,107 PRE_OPEN rows) has been executed and verified in an isolated test schema with zero errors.
   - `BUG-STAGE1-CLI-CWD-RELATIVE-PATHS` is eliminated. Stage 1 evaluates to `COMPLETE` from any working directory.
2. **Operational Schedule Approved:**
   - Decision `SCHEDULE` is formally approved with **PRE_OPEN Option B** (09:22 IST, waiting for pre-open replay completion).
   - In accordance with production gating rules, the schedule is **prepared but NOT installed** (`# APPROVED_NOT_INSTALLED:`).
3. **Safety Locks Intact:**
   - Production database contains **0 feature rows**, **0 feature runs**, and **0 multi-source news rows**.
   - Production flags remain `False`.
   - Write token remains unset.
   - Installed crontab contains **0 Stage 3 entries**.
4. **Distinction Maintained:**
   Stage 3 has legitimately attained **`PRODUCTION READY`** without executing production, without backfilling, and without unlocking the production environment.
