# Stage 3: current forensic verification

**Performed:** 2026-09-29, 14:03–14:50 IST.
**HEAD:** `df0d861` (code, configuration and tests). This document is committed separately.
**Machine-readable evidence:** `audit/evidence/STAGE_3_CURRENT_FORENSIC_VERIFICATION.json`.

**Evidence classes used below:**

| Class | Meaning |
|---|---|
| **DIRECT** | query, log or test output observed here |
| **DERIVED** | computed from direct evidence |
| **DOCUMENTARY** | configuration, code or a document |

## 1. Executive summary

| State | Status |
|---|---|
| IMPLEMENTATION VERIFIED | yes: tests and gates below |
| PRODUCTION RUN VERIFIED | yes: the 29 Sep manual production run (180,256 + 194,392 rows) |
| SCHEDULE INSTALLED | yes: two approved Stage 3 jobs, plus the daily Stage 2 refresh |
| PRODUCTION ENABLED | yes: `PRAJNA_STAGE3_ENABLED=true`; backfill false |
| CONTROLLED EXECUTION VERIFIED | yes, **with a finding**. Both cron-equivalent reruns of the completed 29 Sep snapshots **failed closed** with `DeterminismMismatch` on one row (`GLOBAL_INDEX\|^DJI:global_ret_1d`). Nothing was overwritten |
| ACTUAL SCHEDULED EXECUTION | **PENDING**: the first cron-triggered runs are 2026-09-30 at 09:00:30 and 09:22 IST |

**New finding F-GLOBAL-FINALITY.**

- **Cause:** the finality of global labels (CONFIRMED / REVISED) is computed from **all** vendor observations, including those made after a snapshot's as_of.
- **What happened:** Upstox revised DJI's 25 Sep close at 12:40:03 IST today, after as_of. A recompute of the 29 Sep snapshots now drops that label and yields −0.00305 instead of the stored 0.00785.
- **The stored value is the correct as-of value.** The label had been confirmed by re-observations before 08:59:59, and the revision came after.
- **The engine refused the rerun, as designed.**
- **Exposure for scheduled runs:** none observed. Global observations happen only at 12:40 and 21:10 IST, outside the 09:00–09:40 run window.
- **Exposure elsewhere:** manual Stage 3 runs after 12:40, recomputes, and backfill.

The Stage 3 gate itself prints `STAGE 3: COMPLETE`, which is its own label: flag on and O PASS. It **does not** cover the scheduled-run evidence, and its criterion O counts COMPLETE runs while ignoring the 2 FAILED controlled runs. This report therefore does **not** call Stage 3 fully complete.

## 2. Current production state (DIRECT)

| Item | Value |
|---|---|
| `PRAJNA_STAGE3_ENABLED` | **true**: `Settings()`, from `backend/.env` (git-ignored, mode 0600) |
| `PRAJNA_STAGE3_BACKFILL_ENABLED` | **false**: explicit line in `.env` |
| Write token | `PRAJNA_WRITE_TOKEN` in `.env`; never printed, never in cron or argv (`--token-from-dotenv` reads it at run time into the environment) |
| Kill switch | off (`backend/var/run/stage3.kill` absent after the release in §10) |
| Crontab | 19 active lines. Stage 3: `0 9 * * 1-5 … sleep 30 && ops/runbooks/stage3_snapshot.sh PRE_SESSION --token-from-dotenv`, and `22 9 * * 1-5 … stage3_snapshot.sh PRE_OPEN --after-replay --token-from-dotenv`. Stage 2 refresh: `30 5 * * * … acceptance stage2 --run-tests --md ''` |
| systemd timers (prajna or stage3) | 0 system, 0 user |
| `feature_value` | 374,648 (2026-09-29 only) |
| Stage 3 runs | 5: 3 COMPLETE, 2 FAILED (controlled reruns, §9 and §12) |
| `stage3_event` | 16 rows (§7) |

## 3. Stage 1 dependency

`prajna acceptance stage1` at 14:28 IST (DIRECT): **OVERALL: COMPLETE**, with 25 criteria:

- 19 PASS;
- 4 DEFERRED (G, I, J, S: BACKFILL-DEFER);
- 2 OUT_OF_SCOPE (H, L).

Every Stage 3 run re-evaluates Stage 1 fresh inside the lock check.

## 4. Stage 2 dependency

`prajna acceptance stage2 --run-tests` at 14:36 IST (DIRECT): **PASS**, 16/16, with P = `1126 passed, 4 skipped`.

- **Formal status:** `app/acceptance/stage2.py:297` defines `overall = "PASS" if every criterion is PASS else "NOT PASSED"` (DOCUMENTARY). **Stage 2 has no COMPLETE state**, so PASS is its terminal status.
- **Lock dependency:** the Stage 3 lock requires this report to be PASS, include P, and be at most 7 days old. This run refreshed it (generated 09:06:22 UTC), and the daily 05:30 job keeps it fresh.

## 5. Stage 3 architecture (DOCUMENTARY)

**Run flow:** cron → `ops/runbooks/stage3_snapshot.sh`:

1. `flock` on `var/run/stage3.lock` (single run; waits up to 300 s);
2. PRE_OPEN only: waits for `replay exit 0` of `preopen_day.sh`;
3. `prajna stage3 run --commit`;
4. inside that: `locks.require`. Every condition is checked (flag, kill switch, Stage 1 fresh, Stage 2 report, decisions, registry, token), and any failure is REFUSED and audited.

**Run mechanics:**

- The run row is committed first.
- One REPEATABLE READ transaction covers compute, then INSERT batches of 2,000 rows (30,000 parameters), then the determinism compare of every stored row, then finalize. The values and COMPLETE status are one commit.
- A RUN_COMPLETE audit event follows in its own commit.

**Not present:** a database advisory lock. Double or concurrent writes are prevented by `flock`, the unique key with insert-or-skip, and the determinism check.

## 6. Existing production run verification (29 Sep)

This comes from a read-only REPEATABLE READ transaction plus a **full read-only recompute** (DIRECT, `baseline_readonly` in the JSON).

| Check | Result |
|---|---|
| PRE_SESSION | run `cb26b9c2`, COMPLETE, 180,256 rows (128,996 values / 51,260 reasons), as_of 08:59:59 IST, one run_id, one xmin |
| PRE_OPEN | run `eb0a0012`, COMPLETE, 194,392 rows (141,982 / 52,410), as_of 09:08:00 IST, one run_id, one xmin |
| Duplicates, orphan runs, orphan instruments, rows of non-COMPLETE runs, value/reason violations | all 0 |
| Registry | one hash, `9061d85b…`, on all 374,648 rows; 61 and 65 feature IDs exactly; 0 `mnews_*` |
| Recompute vs stored (now) | 0 missing and 0 extra keys. **1 value and input-hash difference per snapshot: DJI `global_ret_1d`** (F-GLOBAL-FINALITY). All other 374,646 rows identical |
| Pre-open replay dependency | 3,414 stored `preopen_ieq` values equal the raw last tick before 09:08 (0 mismatches). 117 instruments with a stale previous-session bar are MISSING_INPUT (known finding F1) |

## 7. Database forensics (DIRECT)

**Per snapshot:** PRE_OPEN 194,392 rows; PRE_SESSION 180,256 rows. Each has 1 run_id and 1 distinct xmin.

**Stage 3 runs:**

| Run | Stream | Status | Rows written | IST | Error |
|---|---|---|---|---|---|
| `cb26b9c2` | PRE_SESSION | COMPLETE | 180,256 | 10:35–10:38 | |
| `eb0a0012` | PRE_OPEN | COMPLETE | 194,392 | 10:40–10:44 | |
| `a3dd4baa` | PRE_SESSION | COMPLETE | 0 | 10:46–10:49 | (rerun: 0 inserted) |
| `90e42bd9` | PRE_SESSION | **FAILED** | 0 | 14:19–14:23 | `DeterminismMismatch … GLOBAL_INDEX\|^DJI:global_ret_1d; nothing overwritten` |
| `8f2a59ea` | PRE_OPEN | **FAILED** | 0 | 14:24–14:28 | the same |

**`stage3_event`:**

| ids | Event | When |
|---|---|---|
| 1–4 | REFUSED | 28 Sep lock checks |
| 5–7 | RUN_COMPLETE | 29 Sep first run and rerun |
| 8–11, 13 | REFUSED | §10 |
| 12 / 14 | KILL_ON / KILL_OFF | §10 |
| 15–16 | RUN_FAILED | §12 |

**Other checks:**
- **Pre-open coverage:** `preopen_gap_pct` 3,045, `preopen_ieq` 3,414, `preopen_ieq_to_avg_volume` 3,367, `preopen_imbalance` 3,160 values, each out of 3,534.
- **FII/DII source (28 Sep, knowable 08:32:09 IST):** FII 9,047.56 − 14,400.78 = −5,353.22 and DII 15,918.32 − 10,729.30 = 5,189.02, equal to the stored values at both snapshots.
- **RUNNING Stage 3 runs:** 0.

## 8. PIT verification

| Check | Result | Class |
|---|---|---|
| Stored `input_max_knowable_at >= as_of` | 0 rows | DIRECT |
| as_of values | 08:59:59 and 09:08:00 IST, equal to the calendar (previous session 28 Sep) | DIRECT |
| FII/DII, VIX, 400-stock `ret_1d` sample, all pre-open `ieq` | agree with plain-SQL recomputation | DIRECT |
| Same-session bar available before as_of | none existed | DIRECT |
| Tests (PIT adversarial, including the midnight boundary) | pass: in the 1,126 | DIRECT |
| **F-GLOBAL-FINALITY** | Finality is not evaluated as of the snapshot. The stored values are as-of-correct, because no global observation happened between as_of and the run. This holds for the schedule, since global observations happen only at 12:40 and 21:10 IST (`ohlcv_observation` fetched_at: 12:40 ×223, 21:10 ×247, one manual 17:00 ×62). A recompute or first-time run after a revision or confirmation observed later would differ | DIRECT + DERIVED |

## 9. Idempotency verification

- **The 10:46 rerun `a3dd4baa` (DIRECT):** 0 inserted, 180,256 present, COMPLETE. At that time recompute and stored values were identical.
- **The 14:19 and 14:24 reruns (DIRECT):** **not idempotent**. The DJI revision observed at 12:40 changed one recomputed value. The engine **refused**: DeterminismMismatch, FAILED, rolled back.

  Production is unchanged. `feature_value` stayed at 374,648, the highest row xmin stayed at 185564 (no row inserted or updated), and the stored DJI values stayed at 0.00785407121282.

  **Result:** duplicate-safety and determinism protection are verified. "Same values on rerun" does **not** hold after a later vendor revision of a global label (F-GLOBAL-FINALITY).

## 10. Failure-safety verification

The real production CLI was used where the design writes only an audit row. Counts before and after each case are in the JSON.

| # | Case | Method | Result |
|---|---|---|---|
| 1 | Stage 3 disabled | real CLI, `PRAJNA_STAGE3_ENABLED=false` for the command | REFUSED, exit 3, event 8, 0 feature rows |
| 2a | No token | real CLI | REFUSED `write_token`, exit 3, event 9 |
| 2b | Invalid token | real CLI | REFUSED `write_token`, exit 3, event 10 |
| 3 | Backfill | real CLI `stage3 backfill --commit` with a valid token | REFUSED `backfill_enabled`, exit 3, event 11 |
| 4 | Stage 1 stale or unavailable | tests `test_each_condition_alone_refuses_the_run[_stage1-stage1_complete]` and `[_stage2-stage2_pass]` | PASSED (test database) |
| 5 | Replay failed or missing | scratch copy of the real runbook with a stub CLI (the real log is today's genuine replay) | `STAGE3_SKIP … nothing written`, exit 1, CLI never invoked |
| 6 | Concurrent invocation | real runbook while `var/run/stage3.lock` was held | `STAGE3_SKIP … held … for 3 s`, exit 1, 0 writes |
| 7 | Duplicate invocation | §9 and §12 | 0 duplicate rows; unique key; determinism refusal |
| 8 | Kill switch | real `stage3 kill on` → run → `kill off` | KILL_ON (12), run REFUSED `kill_switch_off` (13), KILL_OFF (14), file absent afterwards |
| 9 | Invalid configuration | real CLI, `PRAJNA_STAGE3_ENABLED=maybe` | `ValidationError`, exit 1, before any lock check; no event, 0 writes |

## 11. Cron verification (DIRECT)

- **Installed Stage 3 lines:** exactly the approved two (09:00:30 = `0 9` plus `sleep 30`; 09:22 with `--after-replay`), each once.
- **Other checks:** no duplicate slot; no token string; working directory `cd $B`; the runbook `ops/runbooks/stage3_snapshot.sh`.
- **Logging:** the runbook tees to `var/logs/daily/stage3_<day>.log`, and cron appends to `var/logs/cron.log`.
- **Locking:** `flock`, as in §10 case 6.
- **Tests:** live cron tests 4/4 PASSED; unit schedule and cron tests pass (in the 1,126).

## 12. Controlled cron-equivalent execution

> **CONTROLLED CRON-EQUIVALENT EXECUTION. This is NOT an actual scheduled-run verification.**

- **Method:** both Stage 3 command lines were taken verbatim from `crontab -l`. They ran under `env -i` with only cron's variables (`HOME`, `LOGNAME`, `SHELL=/bin/bash`, `PATH=/usr/bin:/bin`, `B`, `LK`) via `/bin/bash -c`, at 14:17:45 and 14:23:15 IST. The session is today's (2026-09-29), whose snapshots were already stored.
- **Observed:**
  - both reached the engine through the runbook, `flock`, the lock check (all conditions PASS, including the token from `.env`) and a full compute;
  - both then **failed closed** with `DeterminismMismatch` (runs `90e42bd9` and `8f2a59ea`);
  - runbook markers `STAGE3_FAILED`, exit 1;
  - 0 rows written or changed.
- **This proves:** the cron path, environment loading, token loading, locking and fail-closed behaviour.
- **It does not prove:** a successful scheduled run.

## 13. Full test suite

| Run | Command | Result |
|---|---|---|
| Full suite, as Stage 3 gate criterion K (14:36–14:45) | `prajna acceptance stage3 --run-tests`, i.e. `python -m pytest -p no:randomly` in `backend/` | **1,126 passed, 0 failed, 4 skipped**, 0 errors, 346 s |
| Full suite, as Stage 2 gate criterion P (14:29–14:36) | `prajna acceptance stage2 --run-tests` | 1,126 passed, 4 skipped |
| Live cron tests | `pytest -m live tests/live` | 4 passed |
| Skipped | `tests/live/test_installed_cron.py` ×4 | they need `-m live`, and pass in the run above |

No xfail markers are in use. The go-live changes (commits `40a834a`, `b49b47a`, `1884be4`, `df0d861`) are included.

## 14. Security and lock verification

`prajna stage3 locks` with the token (earlier today) gave RUN **UNLOCKED** and BACKFILL **LOCKED**; without the token, RUN is LOCKED.

The runtime refusals in §10 exercised these conditions against production:
- flag;
- token;
- backfill;
- kill switch.

The Stage 1 and Stage 2 conditions are covered by tests.

## 15. Previously known findings

| Finding | Classification | Evidence |
|---|---|---|
| Stage 1 CLI working-directory paths | **FIXED** | `69a3a94`; identical results from three directories |
| Stage 2/3 CLI default paths | **FIXED** | `1327f75` (outputs), `bcf10e0` (pytest working directory), `1e93993` (test) |
| Crontab drift assertion | **FIXED** | `1327f75` → `b49b47a` (installed state); live 4/4 |
| No database advisory lock | **ACCEPTED RISK** (by design) | `flock`, unique key, determinism; §10 case 6 |
| Stage 1 timing: must be COMPLETE at 09:00:30; the morning job ended 08:32 on the measured days | **NON-BLOCKING**; **PENDING VERIFICATION** at the first scheduled run | an overrun means REFUSED (safe), then a manual rerun |
| Stage 2 report expiry (7 days) | **FIXED** | `1884be4`: daily 05:30 refresh (user decision) |
| Test harness reading production flags | **FIXED** | `df0d861` |
| F1: pre-open features blanked for stale instruments | **NON-BLOCKING** (a definition decision) | post-production audit |
| F2: RUN_COMPLETE event is a separate commit | **NON-BLOCKING** (audit-only gap) | post-production audit |
| **F-GLOBAL-FINALITY** (new) | **NON-BLOCKING for the installed schedule**. **BLOCKING for manual Stage 3 runs after 12:40 IST, recomputes and backfill.** Fixing it is a Stage 2 change (`pit.global_bars` finality as of `as_of`) and needs your decision | §8, §9, §12 |
| Gate criterion O ignores FAILED runs | **NON-BLOCKING** (a reporting gap) | O PASS with `failed_runs: 2` |

## 16. VERIFIED_NOW

Enablement, lock states (RUN unlocked with token, BACKFILL locked), cron content, the cron path under a cron environment, failure safety (cases 1–9), the stored 29 Sep production data (integrity, PIT, atomicity, registry, news isolation), the full test suite, and the three gates.

## 17. PENDING_ACTUAL_SCHEDULED_RUN

These can only be shown at the scheduled time on a trading day (2026-09-30):

1. cron actually fires at 09:00 and 09:22 IST on a weekday, from its own daemon and environment;
2. Stage 1 is COMPLETE at 09:00:30, after the real morning job;
3. a first-time snapshot commits at the scheduled time. PRE_SESSION is expected to finish around 09:05;
4. PRE_OPEN waits for that day's real replay and commits; it is expected around 09:37 and marked `STAGE3_LATE` by design;
5. the scheduled runtimes;
6. the 05:30 Stage 2 refresh runs from cron and keeps the lock's report fresh;
7. no global observation falls between as_of and the run (F-GLOBAL-FINALITY exposure). This is expected from the 12:40 and 21:10 schedule.

## 18. Remaining acceptance criteria

Every Stage 3 gate criterion (A–O) passes now. What remains is operational evidence: §17 items 1–7, plus your decision on F-GLOBAL-FINALITY.

## 19. Exact commands executed (from `backend/`)

```
prajna acceptance stage1 --out <scratch> --md ''
prajna acceptance stage2 --run-tests --md ''
prajna acceptance stage3 --run-tests --md ''
python -m pytest -m live tests/live -p no:randomly
read-only audit: post_prod_audit.py (REPEATABLE READ, READ ONLY) -> baseline_readonly.json
failure_safety.sh: stage3 run --commit (flag off | no token | bad token | kill on) ; stage3 backfill --commit ; stage3 kill on|off ; PRAJNA_STAGE3_ENABLED=maybe stage3 run ; stage3_snapshot.sh with a held flock
env -i HOME LOGNAME SHELL PATH B LK /bin/bash -c "<the two Stage 3 lines from crontab -l>"
read-only forensic SQL (see JSON "db")
```

## 20. Exact evidence

The JSON holds the gate outputs, the counts before and after each failure-safety case, every run and event row, the recompute comparison and the SQL results.

The scratch artefacts are in the session scratchpad `cur/`:

- `baseline_readonly.json`, `final_db.json`;
- `fs_*.txt`;
- `g_s1.json`, `g_s2.json`, `g_s3.json`.

## 21. Final operational status

| State | Status |
|---|---|
| 1. Technically implemented | **VERIFIED** |
| 2. Production-tested | **VERIFIED**: manual production run on 29 Sep, plus controlled reruns (fail-closed) |
| 3. Production-enabled | **YES** |
| 4. Schedule installed | **YES** |
| 5. Safe for daily operation | **YES, for the installed schedule** (fail-closed on every tested fault; F-GLOBAL-FINALITY is not reachable in the 09:00–09:40 window). Manual runs after 12:40 IST need care until F-GLOBAL-FINALITY is fixed |
| 6. Fully acceptance-complete | **NO**: gate A–O PASS, but actual scheduled execution is pending |
| 7. Awaiting actual scheduled-run evidence | **YES**: 2026-09-30, 05:30, 09:00:30 and 09:22 IST |
