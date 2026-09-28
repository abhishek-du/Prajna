# Stage 3: ready-for-unlock review (2026-09-28, evening)

## Verdict

**PRODUCTION READY (technical): YES.**

- `prajna acceptance stage3 --run-tests` at 15:52 UTC: **A–N PASS, O PENDING.**
- Full-universe persistence has actually succeeded, with real commits into an isolated schema of the test database.

**PRODUCTION UNLOCKED: NO. BACKFILL EXECUTED: NO.**

| Level | State | Evidence |
|---|---|---|
| IMPLEMENTED | YES | registry `features-v1`, 65 features (`REGISTRY_SHA256 9061d85b…`) |
| TESTED | YES | Stage 3: **100 passed**. Full suite: **1,112 passed, 2 skipped, 0 failed**. The skips are the live cron tests, `-m live` |
| COMPUTATION VERIFIED | YES | full universe, read-only from production: 3,547 instruments; PRE_SESSION 180,919 rows (140–143 s), PRE_OPEN 195,107 rows (156–159 s) |
| PERSISTENCE VERIFIED | YES, in an isolated test schema | both snapshots committed: 91 + 98 INSERTs of ≤ 30,000 parameters. Atomic, idempotent, deterministic, and a failure leaves no partial snapshot. `audit/evidence/STAGE_3_PERSISTENCE_VERIFICATION.md` |
| DRY-RUN READY | YES | gate A–L PASS |
| PRODUCTION READY | YES | M PASS (Stage 1 COMPLETE, Stage 2 PASS); N PASS (decisions) |
| PRODUCTION UNLOCKED | **NO** | `PRAJNA_STAGE3_ENABLED` false (not in `.env`); no write token supplied; kill switch off (no `var/run/stage3.kill`) |
| PRODUCTION EXECUTED | **NO** | production `feature_value` 0 rows; Stage 3 `ingest_run` 0; `stage3_event` only the 4 REFUSED rows of the morning check |
| BACKFILL EXECUTED | **NO** | `PRAJNA_STAGE3_BACKFILL_ENABLED` false; decision BACKFILL DEFERRED |

Criterion O (production evidence) stays PENDING by design. It needs the first authorised production run; no evidence was manufactured.

## 1. Prerequisites (evaluated 2026-09-28, 20:46–20:48 IST)

| Prerequisite | Result |
|---|---|
| **Stage 1** | **COMPLETE**, identical from `backend/`, the repository root and an unrelated directory after the path fix 69a3a94 (`audit/evidence/stage1_cwd_verification.json`): 20 PASS, G/I/J/S DEFERRED (BACKFILL-DEFER), H/L OUT_OF_SCOPE, 0 failing, 0 waiting. Before the fix, the same gate run from the repository root reported NOT COMPLETE |
| **Stage 2** | **PASS**: report of 2026-09-28 09:16 UTC, 16/16, with tests |
| **Stage 3 decisions** | FEATURE-SCOPE, FEATURE-PARAMS, FEATURE-SNAPSHOTS, FEATURE-NO-SOURCE and FII-DII-STALENESS: all APPROVED (`docs/STAGE_3_DECISIONS.md`) |
| **Locks** (`prajna stage3 locks`, no token) | RUN: every condition PASS except `stage3_enabled` (false) and `write_token` (none), so **LOCKED**. BACKFILL: the same, plus `backfill_enabled` false |

## 2. What changed since the morning review

| Commit | Change |
|---|---|
| 580f587 | FII/DII staleness (decision FII-DII-STALENESS): the previous trading session or MISSING_INPUT; features version 2 |
| c42cb0d | one REPEATABLE READ snapshot for compute + persistence; the dry-run uses the same isolation, READ ONLY |
| 0fa4839 | adversarial point-in-time tests: late bar revision, late first bar, corporate-action revision, delayed statement, VIX with the previous session missing |
| 037a17f | **BUG-STAGE3-PERSIST-PARAM-LIMIT fixed**: INSERT batches are sized from a bind-parameter budget (2,000 rows = 30,000 parameters < 32,767). Before, 5,000 rows = 75,000 parameters, and **every full-universe production run would have failed** at persistence |
| 42570c0 | full-universe persistence verification tool and evidence |
| 69a3a94 | **BUG-STAGE1-CLI-CWD-RELATIVE-PATHS fixed**: the Stage 1 gate's files and default outputs are anchored to the project |
| 2274c40 | production schedule documented; runbook and commented cron prepared |
| (this commit) | **SCHEDULE APPROVED with PRE_OPEN option B** (user, 2026-09-28); cron lines approved, not installed |

## 3. Point in time (tests, all passing)

| Case | Test |
|---|---|
| Late bar revision | `test_late_bar_revision_is_never_used` |
| Previous-session bar first knowable after as_of | `test_previous_session_bar_first_observed_after_as_of` |
| Corporate action (new, or a revision) knowable after as_of | `test_action_not_yet_knowable_is_not_applied`, `test_revised_corporate_action_known_after_as_of` |
| Delayed financial statement | `test_delayed_financial_statement` |
| FII/DII published after as_of | `test_publication_after_as_of_is_not_used_and_no_older_day_is_relabelled` |
| Stale FII/DII latest observation | `test_stale_latest_day_is_missing_not_relabelled` |
| Holiday boundary | `test_holiday_boundary_uses_the_calendar_previous_session` |
| India VIX with the previous session missing | `test_india_vix_previous_session_missing` |
| Concurrent commit during a run | `test_a_commit_during_the_run_is_not_observed`. It fails with isolation disabled |

**On real data** (dry-run of the 2026-09-28 PRE_SESSION, 51 instruments, read-only):
- `fii_net_cash_1d` = −3,693.93 and `dii_net_cash_1d` = 2,838.17, which are exactly the 09-25 net figures. 09-25 is the snapshot's previous session, and its figures became knowable at 08:32:10 IST, before as_of 08:59:59.

## 4. Residual risks (known, not blocking; not changed here)

1. **Corporate-action vendor edits.**
   - A vendor edit of a split or bonus is stored as a second event and flagged as a WARN anomaly at ingestion.
   - If both versions became EXACT factors, `pit.bars_adjusted` would apply both once both are knowable.
   - Production today has **0** such duplicates. The 10 same-day pairs found are genuine split + bonus pairs.
   - A human decides which event wins when the anomaly appears.
2. **`news_count_24h` / `news_count_7d` report 0.0 when no linked Upstox news is knowable.** They do not prove that news ingestion ran, which is Stage 1 criterion N's job.
3. **The Stage 2 and Stage 3 gates share the defect class fixed for Stage 1.**
   - Their test run (`pytest` without a fixed working directory) and their default `--md ../docs/…` outputs depend on the working directory.
   - They were run from `backend/` here, as documented.
   - The fix would be the same anchoring as 69a3a94. It was not part of the verified findings.
4. **Persistence timings come from the test database** of the same PostgreSQL instance. The first production run will measure the real numbers.

## 5. Exact next human decisions

1. ~~SCHEDULE~~: **APPROVED on 2026-09-28 with PRE_OPEN option B.** The cron lines are ready but not installed.
2. **Explicitly authorise the first production run.** This is the only remaining decision. Installing the approved cron lines goes with it (schedule §13). For one session, with the flag given per invocation and nothing persisted, run this from `backend/`:

   ```bash
   export PRAJNA_SUPPLIED_TOKEN="$(grep '^PRAJNA_WRITE_TOKEN=' .env | cut -d= -f2-)"
   PRAJNA_STAGE3_ENABLED=true .venv/bin/prajna stage3 run --session <YYYY-MM-DD> --snapshot PRE_SESSION --commit
   ```

   That run would produce criterion O's evidence. **It has not been run.**

A feature backfill stays DEFERRED. FEATURE-NEWS-V2 stays PENDING, on a separate track; `mnews_*` is not in the registry.

## 6. Safety checks that prevent accidental execution (unchanged; verified)

- **Flags:** `PRAJNA_STAGE3_ENABLED` and `PRAJNA_STAGE3_BACKFILL_ENABLED` both default to false; neither is in `.env`.
- **Fresh re-checks:** Stage 1 is evaluated fresh at every run, and the Stage 2 report must be at most 7 days old, PASS, with its tests.
- **Decisions and registry:** all decisions APPROVED, and the registry consistent.
- **Token at the write path.** It is supplied via the environment only.
- **Lock checks:** in the CLI and again inside `engine.run_snapshot`. Every refusal is audited in `stage3_event`, exits 3, and writes nothing.
- **Kill switch:** checked before a run and between instruments.
- **`--commit` is mandatory.** The dry-run is read-only.
- **Storage:**
  - append-only `feature_value`;
  - `ck_feature_pit` and `ck_feature_value_or_reason`;
  - idempotent inserts, and a determinism check that fails instead of overwriting;
  - one REPEATABLE READ transaction and one COMMIT per snapshot.
- **No cron entry installed.** The schedule is approved (option B), but its lines stay commented until production is authorised.
- **No vendor import** in `app.features` (criterion J).
- **Tests are refused on any non-test database** (conftest guard).
