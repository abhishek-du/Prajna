# Final pre-production gate: Stage 3

**Verified:** 2026-09-28, 22:10–23:32 IST, by the Claude Code session that built Stage 3. Every result below was produced in this window by the command shown. Nothing was inferred.

**Target state:** PRODUCTION READY + PRODUCTION LOCKED + NO PRODUCTION EXECUTION.

**Scope of verification.** This document replaces an earlier uncommitted draft of the same name written by another agent at 22:37. That draft is kept in the session scratchpad. It had these errors:

- Stage 1 given as "21 PASS"; the true count is 19.
- A persistence test cited that does not exist.
- Test counts from before the last fixes.

**Concurrency caveat.** Another agent committed to `main` and ran tests against `prajna_test` during this window (commits 1327f75, bcf10e0, 996202e). Every measurement below that uses the test database was taken with no other pytest or gate process running; this was checked before each run (`concurrent=0`). One earlier measurement was discarded because it overlapped with that agent's test run (§13).

## 1. Current HEAD

| | |
|---|---|
| Claim | The verified code is `996202e` plus this documentation commit. No application code changed after the verification runs. |
| Command | `git log --oneline -6` |
| Raw result | `996202e docs: update stage2 and stage3 acceptance reports` · `1e93993 test(acceptance): pin the gates' test-suite working directory` · `bcf10e0 fix(acceptance): anchor run_tests subprocess cwd to BACKEND_ROOT in stage2 and stage3` · `1327f75 fix(acceptance): anchor stage2/stage3/news CLI outputs and reconcile installed cron tests` · `975d6b3 stage3: record schedule approval (PRE_OPEN option B), not installed` |
| Note | HEAD was **not** 975d6b3 when this task started. 1327f75, bcf10e0 and 996202e were committed by another agent (git user `cis`). 1e93993 was committed by this session. The working tree also holds untracked files that are not part of this gate: the independent audit's `audit/evidence/*` and `FINAL_INDEPENDENT_*`, and the other tool's `frontend/`, `backend/app/api/` and `docs/API_*`. |

## 2. Stage 1

| | |
|---|---|
| Claim | Stage 1 is COMPLETE, and the result does not depend on the working directory. |
| Command | `cd backend && .venv/bin/prajna acceptance stage1` (23:19 IST). Earlier the same from the repository root and from an unrelated directory (20:46–20:48 IST, `audit/evidence/stage1_cwd_verification.json`) |
| Raw result | `OVERALL: COMPLETE`, rc 0. **25 criteria: 19 PASS** (A B C D E F K M N O P Q R T U V W X Y), **4 DEFERRED** (G I J S, decision BACKFILL-DEFER), **2 OUT_OF_SCOPE** (H L) |
| Interpretation | COMPLETE under the unchanged criteria. The three-directory runs gave identical statuses and identical K/R/X evidence. |
| Evidence | `backend/var/acceptance/stage1.json` (generated 17:49:47 UTC); `docs/STAGE_1_FINAL_ACCEPTANCE.md`; `audit/evidence/stage1_cwd_verification.json` |

## 3. Stage 2

| | |
|---|---|
| Claim | Stage 2 PASSES 16/16 from every working directory. |
| Command | `prajna acceptance stage2 --run-tests`, from the repository root, an unrelated directory and `backend/` (23:04–23:18 IST) |
| Raw result | All three runs: rc 0, `PASS`, A–P all PASS. P: `1122 passed, 4 skipped` in each run |
| Evidence | `audit/evidence/stage2_stage3_cwd_verification.json`; `docs/STAGE_2_ACCEPTANCE.md` (last run, from `backend/`) |

## 4. Stage 3

| | |
|---|---|
| Claim | Stage 3 is PRODUCTION READY. PRODUCTION UNLOCKED and BACKFILL EXECUTED are both **no**. |
| Command | `prajna acceptance stage3 --run-tests`, from the repository root, an unrelated directory and `backend/` (22:42–23:04 IST) |
| Raw result | All three runs: A–N PASS, **O PENDING**, K `1122 passed, 4 skipped`. Levels: IMPLEMENTED YES, TESTED YES, DRY-RUN READY YES, **PRODUCTION READY YES**, PRODUCTION UNLOCKED no, BACKFILL EXECUTED no. `STAGE 3: NOT COMPLETE (PRODUCTION READY)`, rc 1 (the gate exits 0 only when COMPLETE) |
| Interpretation | O needs a committed production snapshot. It is PENDING by design; no evidence for it was manufactured. |
| Registry | 65 features (61 in both snapshots, 4 in PRE_OPEN only), `features-v1`, `REGISTRY_SHA256 9061d85b3696ab70e566d8257ecb13466930792a74f9b1d8308f232331e47188`, read from `app.features.registry` |
| Evidence | `backend/var/acceptance/stage3.json`, `docs/STAGE_3_ACCEPTANCE.md`, `audit/evidence/stage2_stage3_cwd_verification.json` |

## 5. Persistence

| | |
|---|---|
| Claim | A full-universe snapshot persists without exceeding asyncpg's 32,767 bind-parameter limit. |
| Before | 5,000 rows per INSERT × 15 parameters per row (counted from the compiled statement) = 75,000. The real 180,919-row snapshot failed with `InterfaceError: the number of query arguments cannot exceed 32767` |
| Change | 037a17f: batch size = parameter budget 30,000 // 15 = 2,000 rows |
| Test | `TestPersistScale` (3 tests, PASSED at 23:32). With the old 5,000-row chunks, the two database tests fail with the same InterfaceError |
| Full-universe experiment | Computed read-only from production (3,547 instruments, 2026-09-28), then persisted with real COMMITs into an isolated schema of `prajna_test`, which was dropped afterwards. PRE_SESSION: 180,919 rows, 91 INSERTs (max 30,000 parameters), 72.6 s. PRE_OPEN: 195,107 rows, 98 INSERTs, 76.8 s. No InterfaceError, 0 duplicate keys, 0 PIT violations; `public.feature_value` of the test database was 0 before and 0 after |
| Evidence | `audit/evidence/stage3_persistence_full_universe.json`, `audit/evidence/STAGE_3_PERSISTENCE_VERIFICATION.md` (commit 42570c0) |

## 6. Point-in-time safety

`pytest -rA tests/stage3 -k …` (23:31 IST): every test named below was **PASSED**.

| Item | Test(s) |
|---|---|
| FII/DII staleness | `test_stale_latest_day_is_missing_not_relabelled`, `test_five_day_window_ending_before_the_previous_session_is_missing`, `test_publication_after_as_of_is_not_used_and_no_older_day_is_relabelled`, `test_holiday_boundary_uses_the_calendar_previous_session` |
| REPEATABLE READ | `test_a_commit_during_the_run_is_not_observed`, `test_the_production_session_sets_repeatable_read_itself`, `test_a_run_refuses_without_a_consistent_snapshot` |
| Adversarial PIT | `test_late_bar_revision_is_never_used`, `test_previous_session_bar_first_observed_after_as_of`, `test_revised_corporate_action_known_after_as_of`, `test_delayed_financial_statement`, `test_india_vix_previous_session_missing`, `test_look_ahead_probe[PRE_SESSION]`, `test_look_ahead_probe[PRE_OPEN]` |

On real data (read-only dry-run of 2026-09-28 PRE_SESSION, 51 instruments):
- `fii_net_cash_1d` = −3,693.93 and `dii_net_cash_1d` = 2,838.17. These equal the 09-25 net figures in `macro_observation`, and 09-25 is the snapshot's previous session.
- Those figures became knowable at 08:32:10 IST, before as_of 08:59:59.

## 7. Atomicity and idempotency

| Claim | Evidence (all PASSED or measured) |
|---|---|
| **Atomic:** one transaction and one COMMIT per snapshot; no partial snapshot | Full universe: a second connection saw 0 rows before COMMIT, then all rows. A failure injected after the first INSERT batch left 0 rows. `test_a_failure_after_a_batch_leaves_no_partial_snapshot`, `test_exception_rolls_back_then_retry_succeeds`, `test_crash_is_reaped_and_the_rerun_completes` |
| **Idempotent** | Full universe: the rerun inserted 0 (180,919 present), and an independent recompute inserted 0. `test_run_writes_then_rerun_is_idempotent`, `test_rows_across_several_batches_persist_then_rerun_is_idempotent` |
| **Determinism protection** | Full universe: one tampered value gave `DeterminismMismatch … nothing overwritten`, and the stored value was unchanged. `test_determinism_mismatch_never_overwrites` |

## 8. Locks and safety controls

| | |
|---|---|
| Command | `env -u PRAJNA_SUPPLIED_TOKEN -u PRAJNA_STAGE3_ENABLED -u PRAJNA_STAGE3_BACKFILL_ENABLED prajna stage3 locks --mode RUN` / `--mode BACKFILL` (23:33 IST; read-only) |
| Raw result (RUN) | `FAIL stage3_enabled` · `PASS kill_switch_off` · `PASS stage1_complete` · `PASS stage2_pass (17:48:51 UTC)` · `PASS decisions_approved` · `PASS registry_consistent` · `FAIL write_token AuthorizationError` → `STAGE 3 RUN: LOCKED` |
| Raw result (BACKFILL) | the same, plus `FAIL backfill_enabled` → `STAGE 3 BACKFILL: LOCKED` |
| Flags | `Settings().PRAJNA_STAGE3_ENABLED = False` and `PRAJNA_STAGE3_BACKFILL_ENABLED = False`. `.env` has no `PRAJNA_STAGE3_*` line |
| Token | `PRAJNA_SUPPLIED_TOKEN` is not in the environment. No token was supplied or created |
| Kill switch | `backend/var/run/stage3.kill` does not exist |
| Lock tests (PASSED) | `test_each_condition_alone_refuses_the_run` for flag off, kill switch, stale Stage 1, failing Stage 2 and a pending decision; plus `test_bad_token_refuses`, `test_defaults_refuse_everything`, `test_backfill_needs_its_own_flag`, `test_kill_switch_mid_run` |

## 9. Production schedule

| | |
|---|---|
| Decision | SCHEDULE **APPROVED** by the user on 2026-09-28, with **PRE_OPEN option B** (commit 975d6b3) |
| PRE_SESSION | as_of 08:59:59 IST; start 09:00:30 |
| PRE_OPEN | as_of 09:08:00 IST; start 09:22 with `--after-replay`, which waits for `replay exit 0` of `preopen_day.sh`. The measured replay is 09:20–09:33, so the snapshot is available at about 09:37, after the open. A failed replay means no PRE_OPEN snapshot that day |
| Prepared lines | `backend/ops/cron/prajna.cron:57` `# APPROVED_NOT_INSTALLED: 0 9 * * 1-5 … stage3_snapshot.sh PRE_SESSION --token-from-dotenv`; `:61` `# APPROVED_NOT_INSTALLED: 22 9 * * 1-5 … stage3_snapshot.sh PRE_OPEN --after-replay --token-from-dotenv` |
| Documentation | `docs/STAGE_3_PRODUCTION_SCHEDULE.md`, `docs/STAGE_3_DECISIONS.md` |

## 10. Cron and systemd installation state

| Check | Command | Raw result |
|---|---|---|
| Installed crontab | `crontab -l` | 50 lines, 16 active jobs, **0** lines mentioning stage3 |
| Active jobs vs the prepared file | diff of the active lines | identical |
| Exact text vs the prepared file | `diff <(crontab -l) ops/cron/prajna.cron` | differs, **only** by the commented Stage 3 block |
| systemd timers | `systemctl list-timers --all` and `systemctl --user list-timers --all`, filtered by prajna/stage3 | 0 and 0; no prajna or stage3 unit files |
| Cron tests | `pytest -m live tests/live/test_installed_cron.py`: **4 passed**. `tests/unit/test_stage3_schedule.py` + cwd tests: **15 passed** | |

**TEST-CRONTAB-DRIFT-ASSERTION.**
- *Before:* the old live test asserted `crontab -l == prajna.cron` as exact text, which is false in the intended state, because of the commented Stage 3 block.
- *Fix (1327f75, by the other agent; reviewed):* the tests now separate four things.
  - **A.** Canonical prepared jobs: active jobs are equal.
  - **B.** Approved-not-installed entries: exactly 2 lines, both `# APPROVED_NOT_INSTALLED:`.
  - **C.** The actually installed crontab.
  - **D.** The safety requirement: 0 Stage 3 jobs installed.

## 11. News separation

| Check | Raw result |
|---|---|
| `mnews_*` in the registry | 0. Legacy news features: `news_count_24h`, `news_count_7d`, `news_hours_since_last` |
| FEATURE-NEWS-V2 | `PENDING` (`app/features/news_features.py`) |
| Multi-source production rows (read-only counts) | `news_item`, `news_item_observation`, `news_story`, `news_story_member`, `news_poll`, `news_content`, `news_ai_enrichment`, `news_assessment`, `news_classification`, `news_entity_link`, `news_entity_mention`: all **0**. `news_audit` has 2 rows, both REFUSED SHADOW attempts (the locks working). `news_article` 197 and `news_instrument` 604 are the existing Stage 1 Upstox data |

## 12. Production database state

Command: a read-only transaction on the `prajna` database, 23:1x IST.

| Table | Raw result |
|---|---|
| `feature_value` | **0** |
| `ingest_run where source = 'PRAJNA_STAGE3'` | **0** |
| `stage3_event` | `REFUSED: 4`. The latest was at 09:30:18 UTC this morning (the earlier lock verification), and **no new rows** since |

Nothing in this verification wrote to production. The production database was only read. Every write went to `prajna_test`, and the test runs left it with 0 rows in `feature_value`, `stage3_event` and `ingest_run`.

## 13. Findings

| Finding | Before (measured) | Change | After (measured) |
|---|---|---|---|
| **BUG-CLI-STAGE2-STAGE3-DEFAULT-PATHS-UNANCHORED** | The pre-fix code (975d6b3, run in a scratch worktree from its root): the JSON went to a rogue `<root>/var/acceptance/stage3.json`, then `FileNotFoundError` writing `../docs/STAGE_3_ACCEPTANCE.md`. That path resolves **above** the repository, so a directory there would have received the document | 1327f75 (other agent; reviewed): default `--out`/`--md` anchored like the Stage 1 fix. An explicit path stays relative to the caller | Six runs from 3 directories: outputs updated at `backend/var/acceptance/*.json` and `docs/STAGE_{2,3}_ACCEPTANCE.md`, **no stray files** (`/home/cis/windows/docs`, `<root>/var` and `<unrelated>/var` all absent) |
| **Gate test-subprocess working directory** (found in this task; part of the same finding) | From the repository root, pytest rootdir = root with **no configfile**: `99 failed, 738 passed, 4 skipped, 282 errors`, so Stage 2 P and Stage 3 K were **recorded FAIL**. The committed `docs/STAGE_2_ACCEPTANCE.md` at bcf10e0 shows exactly such a run. From an unrelated directory: `no tests collected`, exit 5 | bcf10e0 (other agent): `cwd=BACKEND_ROOT`. 1e93993 (this session): a regression test, which fails when `cwd=` is removed | P and K = `1122 passed, 4 skipped` from all three directories |
| **TEST-CRONTAB-DRIFT-ASSERTION** | The exact-text assertion is false in the intended state | 1327f75 (reviewed) | See §10: 4 live tests passed; 0 Stage 3 jobs installed |
| Measurement discarded | The first from-root full-suite run (22:05) overlapped with the other agent's `pytest backend/tests` run and hit a `DeadlockDetectedError` | — | Not used as evidence. The from-root failure counts above were reproduced identically by the other agent's own gate run, and the cause (no configfile) was confirmed with `--collect-only`, which does not touch the database |
| Residual (not fixed; outside this task) | `prajna acceptance news --run-tests` runs `pytest tests/news` with a relative path and no working directory | — | Run it from `backend/`. News subsystem, separate track |
| Residual (known, not blocking) | A corporate-action vendor edit could be double-applied if both versions became EXACT factors (0 cases in production). `news_count_*` = 0 does not prove ingestion ran | — | Documented in `docs/STAGE_3_READY_FOR_UNLOCK.md` §4 |

## 14. Tests

| Run (23:19–23:32 IST, from `backend/`, `concurrent=0`) | Result |
|---|---|
| `.venv/bin/python -m pytest tests/stage3 -p no:randomly` | **100 passed**, 0 failed, 0 skipped, 0 errors |
| `.venv/bin/python -m pytest -p no:randomly` | **1,122 passed, 4 skipped**, 0 failed, 0 errors. The 4 skips are `tests/live/test_installed_cron.py`, which needs `-m live` |
| `pytest -m live tests/live/test_installed_cron.py` | 4 passed |
| Claim-specific tests (§6–§8) | 30 passed |

Baselines:
- Stage 3: 84 tests originally, 89 after FII/DII, 100 now.
- Full suite: 1,091 before this programme of work; 1,112 before this task; 1,122 now.
- The count includes `tests/unit/test_api_endpoints.py`, which is untracked and belongs to the other frontend/API tool.

## 15. Final pre-production determination

| Level | Determination |
|---|---|
| Computation verified | **YES** (full universe, read-only) |
| Persistence verified | **YES** (full universe, isolated test schema, real commits) |
| PRODUCTION READY | **YES**: Stage 3 gate A–N PASS from every working directory |
| PRODUCTION UNLOCKED | **NO** |
| PRODUCTION EXECUTED | **NO** |
| BACKFILL EXECUTED | **NO** |

The gate is clean. No finding in scope is open.

## 16. Exact human authorization required

```text
PRODUCTION EXECUTION: NOT AUTHORIZED
STAGE 3 ENABLED: FALSE
BACKFILL ENABLED: FALSE
STAGE 3 CRON INSTALLED: NO
PRODUCTION FEATURE VALUES: 0
PRODUCTION STAGE 3 RUNS: 0
CHECK O: PENDING
```

The next step needs one explicit decision from the user: **authorise the first production Stage 3 run**, naming the session and snapshot. That authorisation covers three actions:

1. Supplying the write token through the environment for that run.
2. Setting `PRAJNA_STAGE3_ENABLED=true` for that invocation.
3. Optionally, afterwards, removing the `APPROVED_NOT_INSTALLED:` prefix from the two cron lines and installing the file (schedule §13).

None of these has been done.
