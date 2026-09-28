# Stage 3: feature engineering (design)

**Status, 2026-09-28:** the code is implemented, tested and dry-run ready. **Production execution is locked. No Stage 3 historical backfill has run.** The generated verdict is `docs/STAGE_3_ACCEPTANCE.md`; regenerate it with `prajna acceptance stage3 --run-tests`.

## 1. Scope (derived from the repository; nothing invented)

There is no written Stage 3 specification in the repository. The scope comes from three sources:

1. **The user's architecture diagram**, stage 3 "Feature Engineering": convert raw data into meaningful features according to the strategy. It has six groups:
   - price & technical;
   - volume & liquidity;
   - fundamental;
   - event;
   - market context;
   - pre-open.

   The strategy is overnight + pre-open. Stage 4 predicts "opportunities for the next session (pre-open)".
2. **The Stage 2 prompt's pipeline**, where Stage 3 = Feature Engineering. Models, signals, risk, execution and monitoring (Stages 4–8) are **out of scope**.
3. **The repository contracts:**
   - `app/canon/pit.py` is "the contract Stage 3 consumes";
   - Stage 2 criterion O ("Stage 3 can consume the canonical data safely");
   - `docs/STAGE_3_READINESS_GATE.md` §6;
   - decision BACKFILL-DEFER.

**User decisions (2026-09-28), recorded in `app/features/decisions.py`:**

| Decision | Status | Content |
|---|---|---|
| FEATURE-SCOPE | APPROVED | the six diagram groups; Stages 4–8 out of scope |
| FEATURE-PARAMS | APPROVED (2026-09-28) | indicator windows the diagram does not name are *conventional*; the registry marks them PROPOSED (their origin), and the user approved them |
| FEATURE-SNAPSHOTS | APPROVED | two snapshots per trading session, PRE_SESSION and PRE_OPEN |
| FEATURE-NO-SOURCE | APPROVED | diagram items with no data source are registered UNSUPPORTED, naming the missing source; nothing is approximated |

## 2. Registry (`app/features/registry.py`, version `features-v1`)

The registry holds 65 features and covers all 31 diagram items:

| Items | Count |
|---|---|
| IMPLEMENTED | 19 |
| PARTIAL | 6 |
| UNSUPPORTED | 4 |
| UNKNOWN | 2 |

Every definition is hashed into `REGISTRY_SHA256`, and every stored value carries that hash and its `feature_version`.

| Group | Features | Parameters |
|---|---|---|
| Price & technical | `ret_1d/5d/20d` | SPECIFIED |
| Price & technical | `sma_20/50/200`, `close_to_sma_*`, `ema_12/26`, `rsi_14` (Wilder), `macd_line/trigger/histogram` (12/26/9), `atr_14`, `atr_pct_14`, `volatility_20` (annualised √252), `beta_60` (vs NIFTY 50, common dates), `dist_high_20`, `dist_low_20`, `breakout_20`, `breakdown_20` | PROPOSED |
| Volume & liquidity | `avg_volume_20`, `volume_spike_20` (last / mean of the 20 before), `turnover_20` | PROPOSED |
| Fundamental | `pe`, `pb`, `roe_pct`, `roce_pct`, `ev_ebitda`, `pe_to_sector`, `pb_to_sector` (vendor `key_ratios`); `revenue_yoy`, `pat_yoy`, `eps_yoy`, `revenue_yoy_q`, `pat_yoy_q`; `liabilities_to_assets` | from vendor data |
| Event | `ca_days_since_*` and `ca_days_to_*` (any, dividend, split, bonus); `news_count_24h/7d`; `news_hours_since_last` | SPECIFIED |
| Market context | `index_ret_1d/5d` and `index_close_to_sma_50` (NIFTY 50, NIFTY BANK); `india_vix_level`; `india_vix_change_5d` (points); `fii/dii_net_cash_1d/5d`; `global_ret_1d` (confirmed labels only); `sector_rs_20` (ret_20d − median of ≥ 3 point-in-time sector members) | mixed |
| Pre-open (PRE_OPEN only) | `preopen_gap_pct` (IEP / previous close − 1), `preopen_imbalance`, `preopen_ieq`, `preopen_ieq_to_avg_volume` | SPECIFIED, except the last (PROPOSED) |

**UNSUPPORTED (no source):**

| Item | Missing source |
|---|---|
| Earnings surprises | no consensus estimates |
| Earnings dates | no earnings calendar |
| Analyst upgrades/downgrades | no analyst ratings |
| All-day order-book imbalance | needs a live tick store (Stage 7) |

The bid-ask spread, news *sentiment* and pre-open-specific events are the UNSUPPORTED halves of PARTIAL items.

**UNKNOWN (no definition anywhere):**
- "Sector/market events";
- "Market regime (bull/bear/sideways)".

Support/resistance levels beyond the 20-session range are the UNKNOWN half of a PARTIAL item.

## 3. Snapshots and point-in-time rules

| Snapshot | as_of (normal session) | Adds |
|---|---|---|
| PRE_SESSION | pre-open start − 1 s = **08:59:59 IST** | — |
| PRE_OPEN | pre-open start + 8 min = **09:08:00 IST** | the pre-open book |

Times come from `trading_session`. A session with no pre-open window (some special sessions) has no PRE_OPEN snapshot, and its PRE_SESSION is open − 1 s. A non-trading day has no snapshot.

**Input rules:**
- Every input is read through `app.canon.pit` with strict `knowable_at < as_of`.
- Each input group records its content hash and its latest `knowable_at`. A value stores `input_max_knowable_at`, and the database checks `< as_of` (`ck_feature_pit`).
- Any input with `knowable_at >= as_of` raises `LookAhead`, and the run fails loudly.
- No bar of the snapshot's own session, or later, is ever used.

**Staleness.** Bar-based features describe the **previous** session. If that session's bar is not knowable at as_of (late or missing ingestion), they are MISSING_INPUT; an older bar is never silently relabelled.

This was found on real data: AASTHA's 2026-09-25 bar was first recorded on 09-28 at 10:46 IST.

**Price basis.** Stock bars come from `pit.bars_adjusted`, so split and bonus factors are applied only when knowable at as_of.
- LOW-confidence rows are refused and never used. These are vendor-adjusted rows older than the corporate-action horizon, rows with an unknown treatment, and rows with no recorded basis.
- RECONSTRUCTED rows are refused too.
- Index bars need no adjustment.
- On real data the horizon leaves about one year of HIGH-confidence daily history, so `sma_200` is available but longer windows would not be.

## 4. Missing data

A null value always carries exactly one reason:

| Reason | Meaning |
|---|---|
| MISSING_INPUT | the input does not exist yet, or is stale |
| INSUFFICIENT_HISTORY | fewer usable observations than the window |
| MALFORMED_INPUT | the vendor payload did not have the expected shape |
| NOT_APPLICABLE | the feature does not apply here |
| DIVISION_UNDEFINED | zero or non-positive denominator, or growth from a loss |
| UNSUPPORTED | no data source exists |
| UNKNOWN | no definition exists |

Nothing is filled, interpolated or defaulted. Values are normalised to 12 significant digits.

**Vendor finding (2026-09-28).** The vendor's *quarterly* income statement carries ANNUAL (March) periods identical to the yearly one for about 99% of instruments (20 of 2,431 differ). `revenue_yoy_q` and `pat_yoy_q` therefore refuse such payloads as MALFORMED_INPUT instead of duplicating the annual growth.

## 5. Storage (migrations 0011 and 0012; additive; backed up first)

**`feature_value`** holds one row per (key, session, snapshot, feature, version):
- the columns are `scope`, `instrument_key`/`instrument_id`, `as_of`, `value` (unconstrained numeric, from 0012) XOR `reason`, `inputs_sha256`, `input_max_knowable_at`, `registry_sha256`, `computed_at` and `run_id`;
- a trigger makes it append-only;
- the checks are value-or-reason, PIT, scope and snapshot.

**`stage3_event`** is the append-only audit. Events are REFUSED, KILL_ON, KILL_OFF, RUN_COMPLETE and RUN_FAILED.

Migration 0012 was needed because `numeric(30,12)` kept 12 decimal places, which truncated small values. The Stage 3 tests caught it when the determinism check refused the rerun.

**Backups:**
- `prajna_20260928T1329_stage3_pre_0011.dump`
- `prajna_20260928T1354_stage3_pre_0012.dump` (sha256 `770daef9…`)

Both are verified.

## 6. Execution modes and locks (`app/features/locks.py`)

| Mode | Writes | Allowed |
|---|---|---|
| unit and integration tests | the test database only (conftest guard) | always |
| **dry-run** `prajna stage3 compute` | nothing (read-only transaction) | always; needs no lock or token |
| **production run** `prajna stage3 run --session D --commit` | `feature_value` | only when **all** of the conditions below hold |
| **feature backfill** `prajna stage3 backfill --from --to --commit` | `feature_value` | all of the run conditions, **plus** `PRAJNA_STAGE3_BACKFILL_ENABLED=true` (default false) |

The production-run conditions are:
- `PRAJNA_STAGE3_ENABLED=true` (default false);
- the kill switch `var/run/stage3.kill` is absent;
- Stage 1 is COMPLETE, **evaluated fresh at that moment**;
- the Stage 2 report is PASS, at most 7 days old, with its tests (P) PASS;
- every decision is APPROVED;
- the registry is consistent;
- a write token is supplied.

**Enforcement:**
- The locks are checked in the CLI and again inside `engine.run_snapshot` (defence in depth).
- Every refusal names each unmet condition, writes a `stage3_event` row and exits 3.
- The kill switch (`prajna stage3 kill on|off`) is also checked between instruments during a run.
- Stage 3 has no vendor call. A test and criterion J assert that `app.features` imports no vendor, network or fetch module; the only `app.ingest` import is the run ledger.
- Stage 3 never starts a Stage 1 warm-up or backfill.
- **No cron entry** exists for Stage 3.

**Run mechanics:**
- One `IngestRunner` run per snapshot: source `PRAJNA_STAGE3`, stream `features.<snapshot>`. `ops status` has a `stage3` family.
- Rows are inserted with `on conflict do nothing`, and every existing row must equal the recompute: a rerun inserts 0 rows, and a disagreement fails the run with `DeterminismMismatch`. It is never an overwrite.
- A compute exception rolls the run back (FAILED, RUN_FAILED).
- A crashed run is aborted by the orphan reaper, and the rerun completes.
- A restart resumes by skipping identical rows.

## 7. Surfaces

- **CLI:**
  - `prajna stage3 registry | locks | compute | run | backfill | kill`
  - `prajna acceptance stage3 [--run-tests]`
- **Read API** (stored values only; see `docs/API_CONTRACT.md`):
  - `GET /v1/stage3/status`
  - `GET /v1/stage3/registry`
  - `GET /v1/instruments/{key}/features?session=&snapshot=&as_of=`
- **Web and frontend:** unchanged.

## 8. Tests (`backend/tests/stage3/`, 84 tests)

| File | What it covers |
|---|---|
| `test_compute.py` | pure functions against hand-computed values; malformed and missing inputs; the reason contract |
| `test_registry_locks.py` | diagram coverage, snapshot instants, the import guard, the kill switch, the Stage 2 report rules |
| `test_engine.py` | runs on a fully specified seed world (`tests/support/stage3_seed.py`); see the list below |
| `test_surfaces.py` | the read API, and the acceptance levels (tests passing never make Stage 3 COMPLETE) |

`test_engine.py` covers:
- the normal path, with values checked by hand;
- a 1:1 bonus adjusting exactly;
- an action not yet knowable not being applied;
- LOW-confidence bars refused;
- the knowable_at boundary to the microsecond;
- look-ahead probes at both snapshots;
- the stale previous bar;
- an over-claiming input failing loudly;
- idempotency, the determinism mismatch, rollback and retry;
- crash recovery via the reaper, and restart;
- the kill switch mid-run;
- append-only storage and the PIT check;
- each lock condition alone, the defaults, and the backfill flag.

## 9. Dry-run on real data (2026-09-28)

**Samples:**
- 2026-09-25, RELIANCE, CHAVDA (bonus ex 09-24), AASTHA (bonus ex 09-28), plus 50 sampled stocks, at both snapshots;
- 2026-09-28 PRE_SESSION, AASTHA and RELIANCE.

**Findings:**
- Values match their definitions. For example, RELIANCE on 09-25 has P/E 19.14 and `preopen_gap_pct` −1.57%, and context features are present for 2 indices, VIX, FII/DII and 13 global instruments.
- Nulls by reason at 09-25 PRE_OPEN (52 instruments, 2,885 rows):

  | Reason | Rows |
  |---|---|
  | MISSING_INPUT | 556 |
  | MALFORMED_INPUT | 68 |
  | DIVISION_UNDEFINED | 19 |
  | INSUFFICIENT_HISTORY | 17 |

- Most MISSING_INPUT rows are the corporate-action and news event features, where no event is known, and fundamentals the vendor has not supplied.
- **Throughput** is about 1.3–1.5 s per instrument with sector members included. The full universe would take roughly 50–60 minutes per snapshot. That is acceptable for a pre-open window only if PRE_SESSION starts well before 09:00, so this is a scheduling item for when production is unlocked. It is recorded here and not tuned yet.

## 10. Remaining blockers and UNKNOWNs

**Blockers before production (all outside the code):**
1. **Stage 1 is not COMPLETE.** X (B2 timing) waits for today's session.
2. ~~FEATURE-PARAMS~~: approved by the user on 2026-09-28.
3. The operator must set `PRAJNA_STAGE3_ENABLED=true`.
4. A schedule must be designed, given the throughput above (UNKNOWN: start time and cadence).

**UNKNOWN:**
- whether the feature backfill is required for Stage 3 COMPLETE; it is currently reported as a separate level only (decision BACKFILL-DEFER);
- definitions for market regime and sector/market events;
- whether consolidated statements should fall back to standalone when consolidated is missing (currently consolidated only).
