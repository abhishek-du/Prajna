# Post-production forensic verification: Stage 3, session 2026-09-29

**Scope.** This is a read-only audit of the first authorised production run (29 Sep, 10:34–10:50 IST). It was performed on 29 Sep between 11:00 and 11:40 IST.

**Machine-readable evidence:** `POST_PRODUCTION_FORENSIC_VERIFICATION.json`.

**How it was done.**

- **Read-only transaction.** Every database check ran inside **one REPEATABLE READ, READ ONLY transaction** on the production database `prajna`.
  - `show transaction_read_only` returned `on` at both the start and the end.
  - PostgreSQL refuses any write inside such a transaction.
- **Follow-up queries** (the xmin check, and the universe and pre-open investigations) ran in separate read-only transactions.

**Nothing was written to production.** In particular:

- no Stage 3 run was started;
- `.env`, cron, source code, migrations, feature values and run records were not touched.

**Confidence levels:**

| Level | Meaning |
|---|---|
| **PROVEN** | directly observed in the data |
| **HIGH** | observed, plus a code path that was read |
| **UNPROVEN** | cannot be shown from the available evidence |

## 1. Production database

| Claim | Method | Direct evidence | Result | Confidence |
|---|---|---|---|---|
| Exact row counts | `count(*)` per snapshot | PRE_SESSION **180,256** (128,996 values, 51,260 nulls); PRE_OPEN **194,392** (141,982 values, 52,410 nulls); total 374,648; 0 rows for any other session | as recorded | PROVEN |
| Exact run records | `ingest_run where source='PRAJNA_STAGE3'` | `cb26b9c2` PRE_SESSION, COMMIT, **COMPLETE**, rows_written 180,256. `eb0a0012` PRE_OPEN, COMMIT, **COMPLETE**, 194,392. `a3dd4baa` PRE_SESSION rerun, COMMIT, **COMPLETE**, **0**. All 3 authorised, no error, registry `9061d85b…` | 3 runs, all COMPLETE, 0 RUNNING or FAILED | PROVEN |
| Rows ↔ runs | `count(*) group by run_id` | cb26b9c2 → 180,256; eb0a0012 → 194,392; the rerun owns 0 rows | stored counts equal each run's rows_written | PROVEN |
| Exact stage3_event records | `select * from stage3_event` | ids 1–4: REFUSED (28 Sep lock checks). 5, 6, 7: RUN_COMPLETE for cb26b9c2, eb0a0012, a3dd4baa | 7 rows; no RUN_FAILED | PROVEN |
| Duplicate keys | group by the unique key, `having count(*) > 1` | 0 | none | PROVEN |
| Value ⇔ reason consistency | `(value is null) = (reason is null)`; reasons outside the allowed set | 0 violations; no unknown reason | consistent | PROVEN |
| Missing or partial rows | full read-only recompute of both snapshots, compared by key | `only_recomputed` 0 and `only_stored` 0, for both snapshots | the stored key set equals the expected key set exactly | PROVEN |

## 2. Point-in-time integrity

| Claim | Method | Direct evidence | Result | Confidence |
|---|---|---|---|---|
| as_of values | distinct `as_of` per snapshot; the calendar via `SN.resolve` | PRE_SESSION `2026-09-29T08:59:59+05:30`; PRE_OPEN `2026-09-29T09:08:00+05:30`; one distinct value each, equal to the calendar | correct | PROVEN |
| No input newer than as_of (as recorded) | `input_max_knowable_at >= as_of` | 0 rows. Latest input: PRE_SESSION 08:32:21.3; PRE_OPEN 09:07:59.998 | none | PROVEN (for the recorded provenance) |
| No input newer than as_of (independent) | plain-SQL recomputation from source tables, filtered by `knowable_at < as_of` | FII/DII (4 features × 2 snapshots) match exactly. India VIX level: raw 13.64 = stored 13.64. `ret_1d` for 400 random stocks without corporate actions: **400/400 agree**. Pre-open `ieq`: 3,414 values equal the raw last tick, 0 mismatches. `preopen_imbalance`: 0 mismatches | agrees | PROVEN for the checked features; the other features rest on the recompute and the recorded provenance (HIGH) |
| No same-session daily bar | NSE 1d bars of 29 Sep knowable before 09:08 | 0 exist | cannot have been used | PROVEN |
| FII/DII previous-session rule | `macro_observation` with `knowable_at < as_of`, independently | previous session (calendar) **2026-09-28**; the latest observation is 2026-09-28 (knowable 08:32 IST). 1d: FII −5,353.22, DII 5,189.02 = buy − sell. 5d: the sum of 22, 23, 24, 25 and 28 Sep = −16,267.05 and 18,789.90. Stored values are equal at both snapshots | correct | PROVEN |
| Pre-open used replayed data | raw `preopen_tick` for 29 Sep | 395,746 ticks: 188,415 knowable before 09:08:00 and 207,331 after (the latter not usable). Replay runs 09:20:01–09:32:05. 3,531 of 3,534 instruments had a tick before 09:08. Stored `preopen_ieq` equals the raw last tick for all 3,414 non-null values | used where available | PROVEN |
| Pre-open nulls | as above, plus the reason | 120 null `preopen_ieq`: 3 with no tick; **117 with a valid tick**, all of them the instruments whose previous-session bar is stale (`ret_1d` MISSING_INPUT, 117 = 117) | see finding F1 | PROVEN |

## 3. Determinism and idempotency (no production write)

| Claim | Method | Direct evidence | Result | Confidence |
|---|---|---|---|---|
| The rerun inserted 0 | the run record | `a3dd4baa`: rows_written 0, outcome inserted 0, already_present 180,256; 0 feature rows carry its run_id | 0 inserted | PROVEN |
| Values identical at the rerun | the rerun completed without `DeterminismMismatch`; the engine compares every stored row with the recompute before COMPLETE | status COMPLETE, RUN_COMPLETE event 7, no error | identical at 10:45–10:50 | HIGH (code path + record) |
| Values identical now | a fresh **read-only** recompute of both snapshots in the audit transaction, compared with every stored row (value as a double, reason, `inputs_sha256`) | PRE_SESSION 180,256 = 180,256; PRE_OPEN 194,392 = 194,392. Value differences 0, reason differences 0, input-hash differences 0 | deterministic, 2 h after the run | PROVEN |

## 4. Atomicity

| Claim | Method | Direct evidence | Result | Confidence |
|---|---|---|---|---|
| Each snapshot written by one transaction | the PostgreSQL `xmin` of every row | PRE_SESSION: **1** distinct xmin (185560) across 180,256 rows. PRE_OPEN: **1** (185564) across 194,392 rows | no partial or multi-batch commit | PROVEN |
| Rows and run status committed together | the `xmin` of the run's current row version | the COMPLETE version of cb26b9c2 has xmin 185560, and eb0a0012 has 185564: the same transactions as their rows | atomic | PROVEN |
| No orphaned or incomplete rows | rows whose run is not COMPLETE; RUNNING runs; distinct `computed_at` | 0; 0; 1 per snapshot | none | PROVEN |
| Audit event in the same commit | `xmin` of the RUN_COMPLETE events | 185561, 185565, 185569: **the next transaction**. `IngestRunner.finalize` commits, then `run_snapshot` records the event and commits again | **not** in the same commit (finding F2) | PROVEN |

## 5. Registry integrity

| Claim | Evidence | Result | Confidence |
|---|---|---|---|
| All rows are features-v1 | the one stored `registry_sha256` = `9061d85b3696ab70e566d8257ecb13466930792a74f9b1d8308f232331e47188` = the code; feature_version mismatches 0 | yes | PROVEN |
| No unexpected or missing feature IDs | PRE_SESSION stored 61 = expected 61; PRE_OPEN 65 = 65; unexpected [] and missing [] | yes | PROVEN |
| No `mnews_*` in production | `feature_id like 'mnews%'` = 0 | yes | PROVEN |

## 6. Safety state now

| Item | Evidence | State |
|---|---|---|
| `PRAJNA_STAGE3_ENABLED` | `Settings()` False; no `PRAJNA_STAGE3*` line in `.env` | **false** |
| `PRAJNA_STAGE3_BACKFILL_ENABLED` | `Settings()` False | **false** |
| Write token | `PRAJNA_SUPPLIED_TOKEN` not in the environment; lock `write_token` FAIL | **absent** |
| Kill switch | `backend/var/run/stage3.kill` absent | off |
| Crontab | `crontab -l`: 16 active jobs, **0** Stage 3 mentions | not installed |
| systemd | system and user timers matching prajna or stage3: **0** | none |
| Locks | `locks.check` (read-only): RUN fails `stage3_enabled` and `write_token`; BACKFILL fails those plus `backfill_enabled` | **LOCKED** |

## 7. Production vs the isolated full-universe verification

| Measure | Isolated (session 28 Sep) | Production (session 29 Sep) | Explained by (direct evidence) |
|---|---|---|---|
| Universe | 3,547 | 3,534 | The 29 Sep 06:30 master refresh marked **15** instruments REMOVED_FROM_MASTER (last seen 28 Sep: RAJVIR, SELMC, MORARJEE, …) and added **2** new listings (PARTY-RE, VARMORA): 3,547 − 15 + 2 = 3,534. PROVEN |
| PRE_SESSION rows | 180,919 | 180,256 (−663) | 3,544→3,531 NSE_EQ × 51 features: 13 × 51 = 663; the 3 indices (×50) and 25 context rows are unchanged. PROVEN |
| PRE_OPEN rows | 195,107 | 194,392 (−715) | 13 × 55 = 715. PROVEN |
| Values | 128,944 / 141,867 | 128,996 / 141,982 | Different sessions and data, so equality is not expected. The **same-session** expectation (a read-only recompute of 29 Sep) matches exactly. The per-feature attribution of the cross-session difference is **not** derived here: UNPROVEN, and not needed |
| MISSING_INPUT | 42,779 / 43,764 | 42,124 / 43,020 | As above |

## 8. Binary floating-point observation

| Claim | Evidence | Result | Confidence |
|---|---|---|---|
| Representation only | The column is `numeric` with no precision or scale. All **270,978** stored values equal the exact decimal expansion of an IEEE double (`Decimal(float(v)) == v` for 100%). 0 values have more than 12 significant digits when read as a double. `5189.02000000000043655745685100555419921875` → `float` → `5189.02` | the engine's float is stored exactly; the long tail is that float's binary expansion | PROVEN |
| No correctness or determinism issue | Determinism compares `float(stored) == recomputed` (0 differences on 374,648 rows). The read API returns `float(v)` (`readapi/main.py _f`), so consumers get `5189.02` | none found | PROVEN for the engine and the API. A consumer reading `numeric` directly as a decimal sees the tail (cosmetic) |

## 9. Findings

| # | Finding | Severity | Evidence | Action |
|---|---|---|---|---|
| F1 | For the 117 instruments whose previous-session daily bar was stale, **`preopen_ieq` and `preopen_imbalance` are MISSING_INPUT although a valid pre-open tick exists**. `engine._BAR_INPUTS` contains `preopen`, so staleness blanks every pre-open feature, including the two that use no bar | Low: conservative information loss, **not** a PIT violation (`preopen_gap_pct` and `preopen_ieq_to_avg_volume` legitimately need the bar) | engine.py:197 and :212; 117 = 117 stale instruments | A definition decision for you. Any change is a new feature version. Not changed |
| F2 | The RUN_COMPLETE audit event is committed **after**, not with, the snapshot | Low: a crash between the two commits would leave a COMPLETE run with its values but no RUN_COMPLETE event. Data integrity is unaffected (rows and run status are one transaction) | xmin 185560 vs 185561 | Documentation that says "one commit per snapshot" should read "one commit for the values and run status; the audit event follows". Not changed |
| F3 | Earlier docs referred to a 180,919-row expectation | Info | That was session 28 Sep; the universe changed (§7) | none |
| F4 | 13,280 `news_count_*` rows of value 0 carry no input `knowable_at` | Info: this is the known "0 does not prove news coverage" residual | §1 query A | none |

## 10. Decision table

| Area | Determination | Basis |
|---|---|---|
| Production snapshot integrity | **PASS** | exact counts; keys equal to the recompute; 0 duplicates; 0 value/reason violations |
| PIT safety | **PASS** | 0 inputs ≥ as_of; independent SQL checks agree (FII/DII, VIX, 400 `ret_1d`, all pre-open `ieq`); no same-session bar existed |
| Atomicity | **PASS** (values + run status); audit event separate (F2) | one xmin per snapshot, shared with the run's COMPLETE version |
| Idempotency | **PASS** | rerun inserted 0; the read-only recompute equals all 374,648 rows |
| Registry integrity | **PASS** | one hash = code; 61/65 features exactly; 0 `mnews_*` |
| News separation | **PASS** | multi-source news tables 0 (news_audit: 2 REFUSED SHADOW attempts); FEATURE-NEWS-V2 PENDING |
| Production lock state | **LOCKED** | flags false, no token, no kill file, 0 Stage 3 cron or systemd timers, `locks.check` LOCKED |
| Daily scheduling readiness | **READY FOR YOUR DECISION** | no blocking defect found. F1 is a definition choice you may want to settle first; F2 is audit-only. Nothing has been enabled or installed |

**Daily scheduling is NOT enabled and NO cron is installed.** Enabling it requires your explicit authorisation. It means `PRAJNA_STAGE3_ENABLED=true` in `backend/.env`, plus installing the two `APPROVED_NOT_INSTALLED` cron lines.
