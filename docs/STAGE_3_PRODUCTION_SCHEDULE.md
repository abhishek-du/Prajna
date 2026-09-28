# Stage 3 production schedule (proposed)

> **Decision SCHEDULE: PENDING_APPROVAL.**
> - **NO SCHEDULE IS ENABLED.**
> - **NO CRON ENTRY IS INSTALLED.** The lines in `backend/ops/cron/prajna.cron` are commented out, marked `PENDING_APPROVAL:`; `crontab -l` has no Stage 3 entry.
> - **USER APPROVAL IS STILL REQUIRED.** That covers the schedule, and **the choice between PRE_OPEN option A and option B (§4), which is not made here.**
> - Production execution is also locked independently of any schedule: `PRAJNA_STAGE3_ENABLED=false`, and no write token is supplied.

Status as of 2026-09-28. Every number below is measured, and the evidence is named.

## 1. Snapshot semantics

A snapshot is the feature set as it was **knowable** at a fixed instant, `as_of`.

- Every input must satisfy `knowable_at < as_of` (Stage 2 `app.canon.pit`, re-checked by the engine and by the `ck_feature_pit` CHECK).
- `as_of` is fixed by the trading calendar, **not by the wall clock**. A run started late computes exactly the same values as a run started on time, from the same stored data.
- Two snapshots are taken per trading session (decision FEATURE-SNAPSHOTS, APPROVED):

| Snapshot | as_of (normal session) | Definition | Features |
|---|---|---|---|
| PRE_SESSION | **08:59:59 IST** | pre-open start − 1 s | 61 (all except the 4 `preopen_*`) |
| PRE_OPEN | **09:08:00 IST** | pre-open start + 8 min (the end of pre-open order entry) | 65 |

A special session (for example 2026-09-19, which has no pre-open window) gets PRE_SESSION at open − 1 s and no PRE_OPEN. A non-trading day gets no snapshot; the command reports "skipped".

## 2. Proposed schedule (commented out; see the heading)

| Job | Proposed start | Command |
|---|---|---|
| PRE_SESSION | 09:00:30 IST, Mon–Fri | `ops/runbooks/stage3_snapshot.sh PRE_SESSION --token-from-dotenv` |
| PRE_OPEN, option A | 09:08:30 IST | `ops/runbooks/stage3_snapshot.sh PRE_OPEN --token-from-dotenv` |
| PRE_OPEN, option B | 09:21 IST; waits for the pre-open replay | `ops/runbooks/stage3_snapshot.sh PRE_OPEN --after-replay --token-from-dotenv` |

**Upstream jobs a run depends on** (installed today; measured):

| Job | Measured | Relevance |
|---|---|---|
| 07:00 morning job (previous session 1D, FII/DII, news) | ran 07:00:02 → 08:32:24 IST on 2026-09-25 and 2026-09-28 | leaves ≈ 28 min before 09:00:30 |
| 08:25 `preopen_day.sh` | captures 08:55–09:20, then replays (commits) the ticks: 09:20:00 → 09:32:37 on 09-28 (09:20 → 09:31 on 09-24 and 09-25) | pre-open ticks are **not in the database before ≈ 09:20** |
| 09:10 `maintenance.sh canon` | commits the Stage 2 canonical layer | may commit during a PRE_OPEN run. That is safe: a run reads one REPEATABLE READ snapshot (§11) |

## 3. Measured runtime (full universe, 3,547 instruments, real data of 2026-09-28)

| Phase | PRE_SESSION | PRE_OPEN | Evidence |
|---|---|---|---|
| rows | 180,919 | 195,107 | |
| compute (read-only, from production) | 140.3 s (142.7 s and 143.1 s in earlier runs) | 156.1 s (159.0 s earlier) | `audit/evidence/stage3_persistence_full_universe.json`; `backend/var/measure/stage3_timing.jsonl` |
| persistence (91 / 98 INSERTs of ≤ 30,000 parameters, plus the determinism compare) | 72.6 s | 76.8 s | isolated schema of prajna_test, real COMMIT (`audit/evidence/STAGE_3_PERSISTENCE_VERIFICATION.md`) |
| commit | < 0.05 s | < 0.05 s | same |
| **total (compute + persistence)** | **≈ 213 s (3 min 33 s)** | **≈ 233 s (3 min 53 s)** | |
| rerun (all rows present) | 69.3 s persistence | — | same |

Notes:
- Persistence was measured on the test database of the same PostgreSQL instance, not on production. No production write was made.
- Run start-up (Stage 1 fresh evaluation in the lock check, about 30 s measured for `prajna acceptance stage1`; universe load) comes on top.
- The earlier estimate of 50–60 min per snapshot is **withdrawn**. It came from 20–50-instrument samples, where sector members dominated the time.

## 4. PRE_OPEN: option A or option B (**PENDING_APPROVAL, not chosen here**)

**The fact behind the choice** (measured on 2026-09-24, 09-25 and 09-28): the pre-open capture keeps ticks in its archive until 09:20, then `preopen_day.sh` replays them into `preopen_tick`, committing between 09:20 and 09:33 IST.

- About 188,000 ticks per day are *knowable* before 09:08:00 (their `knowable_at` is the receipt time, which is point-in-time correct).
- But at 09:08:30 **none of them is in the database yet**.

| | Option A: start 09:08:30 | Option B: start 09:21, wait for "replay exit 0" |
|---|---|---|
| as_of | 09:08:00 | 09:08:00 (identical) |
| `preopen_gap_pct`, `preopen_imbalance`, `preopen_ieq`, `preopen_ieq_to_avg_volume` | **MISSING_INPUT for every instrument** (no tick stored yet) | computed from the ticks knowable before 09:08:00 |
| other 61 features | identical to option B | identical to option A |
| expected completion (≈ 3 min 53 s, §3) | ≈ 09:12:30, before the 09:15 open | ≈ 09:37 on the measured days, **after** the 09:15 open |
| if the replay fails or is late | not affected (it does not use the ticks) | skipped: `STAGE3_SKIP`, nothing written, after a 40 min wait (`STAGE3_REPLAY_WAIT`). A snapshot is never computed on a partly replayed pre-open |
| a later rerun the same day | would **fail the determinism check** (the stored values are MISSING_INPUT, a recompute after the replay has values) and never overwrites, so the day keeps its MISSING_INPUT pre-open features | idempotent |
| value | a PRE_OPEN snapshot before the open, but without the pre-open book | the complete pre-open snapshot, available about 20 min into the session |

**The trade-off:** A delivers before the open but adds nothing over PRE_SESSION except features that are all MISSING_INPUT. B delivers the pre-open book, after the open.

A third possibility, **committing pre-open ticks in real time** during the capture, would give both. It is a Stage 1 change and is not proposed here.

**Decision needed:** A, B, or neither.

## 5. Late runs

- A snapshot started or finished late is **still point-in-time correct**: `as_of` does not move, and inputs recorded after `as_of` are invisible, however late the run.
- The runbook marks completion after 09:15 IST as `STAGE3_LATE` in `var/logs/daily/stage3_<day>.log`. Each stored row carries `computed_at`.
- Lateness never changes a value. It only makes the snapshot available later.

## 6. Retry

- A rerun of a snapshot inserts only missing rows (`on conflict do nothing`) and compares **every** already-stored row with the recompute.
  - Identical: inserted 0. Measured on the full universe: 180,919 present, 0 inserted.
  - Different: `DeterminismMismatch`, the run FAILS, and **nothing is overwritten**. Measured: one tampered value was refused, and the stored value was unchanged.
- The runbook never retries by itself. A retry is a manual rerun of the same command.

## 7. Idempotency

This is the retry rule above, plus the unique key `uq_feature_value (instrument_key, session_date, snapshot, feature_id, feature_version)` and the append-only trigger.

The full-universe verification found **0 duplicate keys** after two snapshots, a rerun and an independent recompute.

## 8. Crash and reaper

- The run row (`ingest_run`, RUNNING) is committed before any compute, so a crash leaves evidence.
- Feature values are committed only in the single final COMMIT, so **a crashed run leaves 0 feature values**. No partial snapshot is ever valid or visible.
- The orphan reaper (`maintenance.sh reap`, 06:40 daily) marks a RUNNING run of a dead process as ABORTED.
- A rerun is required; it completes normally. Test: `test_crash_is_reaped_and_the_rerun_completes`.

## 9. Lock re-evaluation, stale Stage 1 or Stage 2

Every run re-checks every lock condition, in the CLI and again inside `engine.run_snapshot`, before the run row is written:

- `PRAJNA_STAGE3_ENABLED`;
- the kill switch;
- **Stage 1 COMPLETE, evaluated fresh** (never a cached report);
- the **Stage 2 report PASS**, at most 7 days old, with its tests;
- decisions APPROVED;
- the registry consistent;
- the write token.

If Stage 1 has become NOT COMPLETE, or the Stage 2 report is stale or failing, the run is:

- **REFUSED** (exit 3);
- recorded in `stage3_event` (REFUSED, with every unmet condition);
- written to **zero** feature values.

The runbook logs `STAGE3_REFUSED` with the failing conditions. Tests: `test_each_condition_alone_refuses_the_run` (one case per condition), `test_defaults_refuse_everything`, `test_bad_token_refuses`.

## 10. Kill switch

- `prajna stage3 kill on --reason ...` creates `var/run/stage3.kill` (audited).
- A run then:
  - is REFUSED at the lock check, if the switch is already on;
  - or stops between instruments (`KillSwitchEngaged`), if the switch is engaged mid-run. The transaction rolls back, the run is FAILED, and **0 feature values** are written.
- Test: `test_kill_switch_mid_run`.

## 11. Atomicity

**One snapshot = one transaction = one COMMIT.** Compute, the determinism check and persistence share one REPEATABLE READ transaction (`engine.consistent_read`). So:

- **Never a partial universe.**
  - Measured: another connection saw 0 of 180,919 rows before the COMMIT, and all after.
  - A failure injected after the first INSERT batch left 0 rows.
- **One database snapshot.** A canon commit during the run, such as the 09:10 maintenance job, is not observed. Test: `test_a_commit_during_the_run_is_not_observed`; it fails with isolation disabled.
- **Persistence stays inside asyncpg's parameter limit.** INSERT batches of 2,000 rows (30,000 parameters) are used. The old 5,000-row batches exceeded the 32,767 limit, and every full-universe run would have failed (BUG-STAGE3-PERSIST-PARAM-LIMIT, fixed in `037a17f`).

## 12. Single run

The runbook takes `flock` on `var/run/stage3.lock`:

- A second start waits up to 300 s (`STAGE3_LOCK_WAIT`), so PRE_OPEN is not lost behind a slow PRE_SESSION.
- It then gives up with `STAGE3_SKIP`, writing nothing.

## 13. What approval would change

The only change is uncommenting the chosen `PENDING_APPROVAL:` lines in `backend/ops/cron/prajna.cron` and installing the file with `crontab`, **after** production is separately authorised (`PRAJNA_STAGE3_ENABLED=true`). Until then, an installed entry would only produce audited REFUSED events.
