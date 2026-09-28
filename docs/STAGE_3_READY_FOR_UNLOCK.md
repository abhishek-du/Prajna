# Stage 3: ready-for-unlock review (2026-09-28)

## Verdict: **NOT YET READY FOR UNLOCK**

Stage 3 is DRY-RUN READY. It is **not** production ready, because one hard prerequisite is unmet: **Stage 1 is not COMPLETE**. Criterion X is still waiting for evidence from today's session.

Nothing has been unlocked:

| Item | State |
|---|---|
| `PRAJNA_STAGE3_ENABLED` | false |
| `PRAJNA_STAGE3_BACKFILL_ENABLED` | false |
| production `feature_value` rows | 0 |
| Stage 3 runs | 0 |
| historical backfill | not started |

| Level | State |
|---|---|
| IMPLEMENTED | YES |
| TESTED | YES: 84 Stage 3 tests; full suite 939 passed, 2 skipped |
| DRY-RUN READY | YES: gate criteria A–L PASS |
| PRODUCTION READY | **NO**: M BLOCKED (Stage 1) |
| PRODUCTION UNLOCKED | **NO** |
| BACKFILL EXECUTED | **NO** |

---

## 1. Prerequisites (re-checked 2026-09-28, 14:40–15:10 IST)

| Prerequisite | Result | Evidence |
|---|---|---|
| Stage 1 COMPLETE (evaluated fresh) | **NOT MET** | NOT COMPLETE: only **X** is WAITING_FOR_EVIDENCE (B1/B2 verified over ≥ 3 sessions; today's session is evaluated after 16:05 IST). 0 FAIL. G/I/J/S are DEFERRED (BACKFILL-DEFER); H/L are OUT_OF_SCOPE. Stage 1 criteria not modified |
| Stage 2 PASS with tests | MET | `prajna acceptance stage2 --run-tests` at 09:16 UTC: **16/16 PASS**. L (resume after failure): `test_crash_rolls_back_and_the_rerun_resumes`, 0 failed canon runs. P: full suite, exit 0, 939 passed, 2 skipped. Stage 2 criteria not modified |
| Stage 3 decisions | MET | FEATURE-SCOPE, FEATURE-PARAMS (approved by the user 2026-09-28), FEATURE-SNAPSHOTS and FEATURE-NO-SOURCE are all APPROVED |
| Registry consistent | MET | `326a3b19…`, unchanged by the approval |
| Kill switch released | MET | `var/run/stage3.kill` absent |
| `PRAJNA_STAGE3_ENABLED` | not set (deliberately) | the operator's decision |
| Write token | not supplied (deliberately) | supplied only by the unlock command |

---

## 2. FEATURE-PARAMS contract

### Rules common to every daily-bar parameter

- **Input timeframe:** daily (1d) bars, labelled by `session_date` (convention D4: a bar is knowable only after its session closes).
- **Source and as_of rule:**
  - Stocks come from `pit.bars_adjusted(key, "1d", as_of)`. Indices (NIFTY 50, NIFTY BANK, India VIX) come from `pit.bars(..., as_of)`.
  - Only rows with `knowable_at < as_of` are used, and only bars with `market_date <` the snapshot session.
  - The fetch window starts 450 calendar days before the session.
  - Each input group records its hash and its latest `knowable_at`. A value stores `input_max_knowable_at`, and the database enforces `< as_of` (`ck_feature_pit`). Any violation raises `LookAhead` and fails the run.
- **Snapshots:**

  | Snapshot | as_of |
  |---|---|
  | PRE_SESSION | pre-open start − 1 s (08:59:59 IST) |
  | PRE_OPEN | pre-open start + 8 min (09:08:00 IST) |

  Daily-bar values are identical at both snapshots.
- **Windows count stored bars, not calendar days.** A missing session (a halt, or a refused bar) is skipped, never filled.
- **Staleness:** if the last usable bar is not the **previous trading session**, every bar-based feature of that instrument is `MISSING_INPUT`. An older bar is never relabelled. Example: AASTHA on 2026-09-28, whose 09-25 bar was first recorded at 10:46 IST.
- **Corporate actions (stocks):**
  - Prices are divided, and volumes multiplied, by the product of EXACT split/bonus factors whose ex-date falls after the bar, is ≤ the as_of market date, and is knowable before as_of.
  - Factors the vendor already baked in are not applied twice.
  - LOW-confidence bars are refused: vendor-adjusted bars older than the corporate-action horizon, bars with an UNKNOWN vendor treatment, and bars with no recorded basis. RECONSTRUCTED bars are refused too. On current data this leaves about one year (≈ 248 sessions) of usable history.
  - Indices have no corporate actions.
- **Missing data:** a value is null exactly when it has a reason:

  | Reason | Meaning |
  |---|---|
  | `INSUFFICIENT_HISTORY` | fewer bars than the minimum |
  | `MISSING_INPUT` | no input, or a stale input |
  | `DIVISION_UNDEFINED` | zero or negative denominator, or a non-finite result |
  | `MALFORMED_INPUT` | a vendor payload with the wrong shape |

  Nothing is interpolated or defaulted.
- **Output:** values are normalised to 12 significant digits.
- **Changing a parameter later:**
  - Every stored row carries `feature_id`, `feature_version` and `registry_sha256`, and rows are append-only.
  - A change must bump that feature's `version` (or use a new id such as `sma_30`). Existing rows stay valid for their version, and the new version is stored alongside them.
  - **Today there are 0 stored rows, so a change now invalidates nothing.** After production starts, a changed definition without a version bump would make a recompute of an already-stored snapshot fail with `DeterminismMismatch`. It fails closed and never overwrites.
  - The version bump is a manual discipline; `registry_sha256` on each row identifies the exact definition set.
- **Recursive indicators (EMA, MACD, RSI, ATR)** are seeded at the start of the available history, so they depend slightly on how much history there is. With about 248 bars, the seed's residual weight is:

  | Indicator | Residual weight |
  |---|---|
  | EMA 26 | ≈ 4 × 10⁻⁸ |
  | EMA 12 | ≈ 8 × 10⁻¹⁸ |

  A change in the usable-history start therefore moves EMA 26 and MACD values at about the 8th significant digit. The determinism check would detect such a change on recompute.

### Parameters

| Parameter | Features | Exact calculation | Min. observations | Implemented |
|---|---|---|---|---|
| **SMA 20 / 50 / 200** | `sma_n`, `close_to_sma_n` (stocks); `index_close_to_sma_50` (NIFTY 50, NIFTY BANK) | `sma_n = mean(close[-n:])`; `close_to_sma_n = close[-1] / sma_n − 1` | n bars (20 / 50 / 200). Fewer gives INSUFFICIENT_HISTORY; sma ≤ 0 gives DIVISION_UNDEFINED | YES |
| **EMA 12 / 26** | `ema_12`, `ema_26` | α = 2/(n+1). Seed e₀ = mean of the first n closes of the available series. Then eₜ = α·closeₜ + (1−α)·eₜ₋₁ to the last close | n bars (12 / 26) | YES |
| **RSI 14** | `rsi_14` | Wilder. Changes Δ = closeₜ − closeₜ₋₁. Seed: mean gain and mean loss of the first 14 changes. Then g = (13g + max(Δ,0))/14 and l = (13l + max(−Δ,0))/14. RSI = 100 − 100/(1 + g/l). l = 0 gives 100 if g > 0, else DIVISION_UNDEFINED | 15 bars | YES |
| **MACD 12 / 26 / 9** | `macd_line`, `macd_trigger`, `macd_histogram` | line = EMA12 − EMA26 (aligned by date); trigger = EMA9 of the line series (seeded with the SMA of its first 9 values); histogram = line − trigger, each normalised first (so exactly 0 when equal) | line: 26 bars; trigger and histogram: 34 bars. With 26–33 bars the line has a value and the other two are INSUFFICIENT_HISTORY | YES |
| **ATR 14** | `atr_14`, `atr_pct_14` | TR = max(H−L, \|H−C₋₁\|, \|L−C₋₁\|) on adjusted OHLC. Seed = mean of the first 14 TRs. Then a = (13a + TR)/14. `atr_pct` = atr / last close | 15 bars | YES |
| **Volatility 20** | `volatility_20` | the 20 log returns ln(Cₜ/Cₜ₋₁) of the last 21 closes; sample standard deviation (divisor 19) × √252 | 21 bars. A close ≤ 0 gives DIVISION_UNDEFINED | YES |
| **Range 20** | `dist_high_20`, `dist_low_20`, `breakout_20`, `breakdown_20` | `dist_high` = close / max(high over the last 20 bars, including the last) − 1; `dist_low` = close / min(low …) − 1. `breakout` = 1 if the last close > max(high of the 20 bars **before** it), else 0; `breakdown` is the same with min(low) | dist: 20 bars; breakout/breakdown: 21 bars | YES |
| **Beta 60** | `beta_60` | Simple daily returns rₜ = Cₜ/Cₜ₋₁ − 1 for the stock (adjusted) and NIFTY 50 (`pit.bars`). Take the last 60 **dates present in both**. β = Σ(x−x̄)(y−ȳ) / Σ(x−x̄)² with x = NIFTY and y = the stock | 60 common return dates (≥ 61 bars each). var = 0 gives DIVISION_UNDEFINED | YES |
| **VIX change 5** | `india_vix_change_5d` (and `india_vix_level`) | close[-1] − close[-6], in **index points** (not a percentage); level = the last close | 6 bars (level: 1). A stale VIX series gives MISSING_INPUT | YES |
| **FII / DII (existing definition)** | `fii_net_cash_1d`, `fii_net_cash_5d`, `dii_net_cash_1d`, `dii_net_cash_5d` | See below | 1d: 1 date; 5d: 5 dates. Fewer gives INSUFFICIENT_HISTORY; no rows give MISSING_INPUT | YES |

Details of the FII/DII definition:
- **Input:** Stage 1 macro series `FII|NSE_EQ|CASH|1D|buy_amt` and `…|sell_amt` (and the DII equivalents), from `pit.macro(as_of)`. The timeframe is one observation per trading day, in INR crore.
- **Calculation:** net = buy − sell per `observation_date`. 1d = the latest observation date knowable before as_of. 5d = the sum of net over the latest 5 observation dates.
- **Missing data:** a day that has only one side makes the whole series MALFORMED_INPUT.
- **Corporate actions:** not applicable.

### Gap in the existing FII/DII definition (open decision FII-DII-STALENESS)

The 1d value is the latest *published* day. It is **not** required to be the previous session.

On real data, FII figures for 2026-09-23 became knowable only on 2026-09-25 at 08:32 IST. So at the **2026-09-24** PRE_SESSION snapshot, `fii_net_cash_1d` would have reported **2026-09-22's** flow.

The bars have a staleness rule; the existing FII/DII definition does not. As instructed, this was **not changed silently**. The options are:

- **(a)** keep "latest published day" as is;
- **(b)** apply the bar rule: `observation_date` must equal the previous session, otherwise MISSING_INPUT.

The user has not chosen.

### Beta note

The stock series has the staleness rule. NIFTY is not separately required to be current: if NIFTY's previous-session bar were missing, beta would use the last 60 common dates ending earlier. NIFTY's daily bar has been present every session so far.

### The other approved windows (part of FEATURE-PARAMS, for completeness)

| Features | Calculation | Min. observations |
|---|---|---|
| `avg_volume_20` | mean volume of the last 20 bars | 20 |
| `volume_spike_20` | last volume / mean volume of the 20 bars before it | 21 |
| `turnover_20` | mean(close × volume) over 20 bars, which is unchanged by adjustment | 20 |
| `fii/dii_net_cash_5d` | as above | 5 dates |
| `sector_rs_20` | stock ret_20d − median ret_20d of the other members of its point-in-time sector | ≥ 3 members with a value |
| `preopen_ieq_to_avg_volume` | IEQ / avg_volume_20 | 20 bars and a pre-open tick |

### Not given values (no source, or no definition)

| Diagram item | Status | Why |
|---|---|---|
| Market regime (bull/bear/sideways) | **UNKNOWN** | no definition in any source; choosing one is a modelling decision |
| Sector/market events | **UNKNOWN** | no definition in any source |
| Support/resistance *levels* (beyond the 20-session range) | **UNKNOWN** (the PARTIAL item's other half) | no definition |
| Earnings surprises | **UNSUPPORTED** | no consensus estimates in any source |
| Earnings dates | **UNSUPPORTED** | no earnings calendar (the corporate-action feed has dividend, split, bonus and rights only) |
| Analyst upgrades/downgrades | **UNSUPPORTED** | no analyst-rating source |
| All-day order-book imbalance | **UNSUPPORTED** | no live tick store (Stage 7); the pre-open imbalance is implemented |
| Bid-ask spread | **UNSUPPORTED** (half of a PARTIAL item) | no quote store |
| News *sentiment* | **UNSUPPORTED** (half of a PARTIAL item) | no sentiment source or approved model; counts and recency are implemented and are not sentiment |
| Pre-open-specific events | **UNSUPPORTED** (half of a PARTIAL item) | no event source |

---

## 3. Acceptance results

### Stage 3 gate

`prajna acceptance stage3 --run-tests`, 2026-09-28 ~09:40 UTC. Result: **NOT COMPLETE (DRY-RUN READY)**.

| # | Result | Evidence |
|---|---|---|
| A registry covers the diagram | PASS | 31 items: 19 IMPLEMENTED, 6 PARTIAL, 4 UNSUPPORTED, 2 UNKNOWN |
| B determinism | PASS | identical recompute at both snapshots |
| C point in time | PASS | 2,488 dry-run rows, 0 violations; 0 stored violations |
| D look-ahead probe | PASS | 2026-09-21 snapshot: 21 bars now exist at or after that session, and 0 were used |
| E corporate actions / price basis | PASS | 302 bars adjusted by knowable actions (AASTHA, CHAVDA, INE524T01029); 898 LOW-confidence bars refused |
| F missing data has a reason | PASS | 0 contract violations |
| G idempotency | PASS | 0 duplicate keys; TestRun covers rerun, mismatch and restart |
| H execution lock | PASS | |
| I backfill lock | PASS | |
| J no vendor imports | PASS | |
| K tests | PASS | 939 passed, 2 skipped |
| L real-data dry-run | PASS | 23 instruments × 2 snapshots of 2026-09-28 |
| M prerequisites | **BLOCKED** | Stage 1 waiting on X |
| N decisions | PASS | all approved |
| O production evidence | PENDING | locked by design |

Criterion F's null breakdown (PRE_OPEN):

| Reason | Rows |
|---|---|
| MISSING_INPUT | 367 |
| MALFORMED_INPUT | 26 |
| INSUFFICIENT_HISTORY | 16 |
| DIVISION_UNDEFINED | 9 |

### Dry-run, 2026-09-28

53 instruments: RELIANCE, CHAVDA, AASTHA plus 50 sampled. Read-only; nothing was written.

| Snapshot | Rows | Values | MISSING_INPUT | MALFORMED_INPUT | DIVISION_UNDEFINED | INSUFFICIENT_HISTORY | Time |
|---|---|---|---|---|---|---|---|
| PRE_SESSION | 2,677 | 1,948 | 633 | 68 | 18 | 10 | 66 s |
| PRE_OPEN | 2,885 | 2,140 | 649 | 68 | 18 | 10 | 77 s |

- **RELIANCE:** every parameter above has a value. For example, sma_200 1370.696, rsi_14 37.40, beta_60 1.227 and `preopen_gap_pct` −0.90%.
- **CHAVDA:** bonus-adjusted, with `ca_days_since_bonus` 4.
- **AASTHA:** its bar features are MISSING_INPUT (stale 09-25 bar), and `ca_days_since_bonus` is 0 (bonus ex today).

### Verification checklist

| Check | Result |
|---|---|
| 84 Stage 3 tests | **84 passed** |
| Full suite | **939 passed, 2 skipped** (both the Stage 2 P run and the Stage 3 K run) |
| Stage 3 acceptance | DRY-RUN READY; M BLOCKED |
| Look-ahead | D PASS on real data. Tests: facts injected at exactly as_of change nothing; a 1 µs boundary; an over-claiming input fails loudly |
| Idempotency | G PASS. Tests: a rerun inserts 0; a mismatch fails without overwriting; restart resumes |
| Missing input | F PASS; staleness guard confirmed on AASTHA |
| Corporate actions | E PASS (302 real adjusted bars). Tests: a 1:1 bonus adjusts exactly; an action not yet knowable is not applied; LOW-confidence bars are refused |
| Production lock | `prajna stage3 run --session 2026-09-28 --commit` → **REFUSED, exit 3**, audited |
| Backfill lock | `prajna stage3 backfill --from 2020-01-01 --to 2026-09-25 --commit` → **REFUSED, exit 3**, audited |
| Production state after all checks | `feature_value` 0 rows; Stage 3 `ingest_run` 0; `stage3_event` 4 REFUSED, nothing else; no Stage 3 cron entry; flags absent from `.env` and the environment |

---

## 4. Remaining blockers

1. **Stage 1 COMPLETE (a hard gate).** X needs today's B1/B2 timing evidence, which is evaluated after 16:05 IST. If X passes and nothing else changes, criterion M passes and the level becomes PRODUCTION READY.
2. **Operator decision:** set `PRAJNA_STAGE3_ENABLED` (see §5).
3. **Recommended before unlock** (not enforced by a lock):
   - **FII-DII-STALENESS:** choose (a) or (b) (§2).
   - **Schedule:** Stage 3 has no cron entry.
     - Throughput is about 1.3–1.5 s per instrument, so a full-universe snapshot takes roughly 50–60 min.
     - A PRE_OPEN run (as_of 09:08) cannot finish before the 09:15 open. A PRE_SESSION run can only start after 08:59:59.
     - So the universe cannot be computed before the open at today's speed. The start time, cadence and a speed-up are UNKNOWN / to be designed.
4. **Before any feature backfill** (a separate decision; still DEFERRED):
   - Usable HIGH-confidence history starts at the corporate-action horizon (2025-09-24), so sessions before about mid-2026 would have `sma_200` INSUFFICIENT_HISTORY.
   - The horizon is today's earliest known ex-date. It is not evaluated as of each past snapshot, and ingesting older corporate actions would move it. Recomputing an already-stored past snapshot would then fail the determinism check (fail-closed, never overwritten).
   - Whether the backfill is needed for Stage 3 COMPLETE is **UNKNOWN**. It is reported as a separate level.

---

## 5. Exact commands (for the operator; NOT run)

Run from `backend/`. The write token is read from `.env` into the environment, never passed on argv, the same way as the runbooks.

**Check first (read-only):**
```bash
.venv/bin/prajna acceptance stage1 --out /tmp/s1.json --md ''   # must print OVERALL: COMPLETE
.venv/bin/prajna stage3 locks                                    # with the flag below, must print UNLOCKED
```

**Unlock production for one session** (per-invocation flag; nothing persisted):
```bash
export PRAJNA_SUPPLIED_TOKEN="$(grep '^PRAJNA_WRITE_TOKEN=' .env | cut -d= -f2-)"
PRAJNA_STAGE3_ENABLED=true .venv/bin/prajna stage3 run --session <YYYY-MM-DD> --snapshot BOTH --commit
```

A persistent unlock would add `PRAJNA_STAGE3_ENABLED=true` to `backend/.env`. That is not recommended until a schedule exists.

**Start a feature backfill** (additionally needs the backfill flag; a range must be chosen, see §4):
```bash
export PRAJNA_SUPPLIED_TOKEN="$(grep '^PRAJNA_WRITE_TOKEN=' .env | cut -d= -f2-)"
PRAJNA_STAGE3_ENABLED=true PRAJNA_STAGE3_BACKFILL_ENABLED=true \
  .venv/bin/prajna stage3 backfill --from <YYYY-MM-DD> --to <YYYY-MM-DD> --commit
```

This is the **Stage 3 feature** backfill. It computes from data already stored. It is not the Stage 1 vendor backfill (the ~293k-window historical fetch), which Stage 3 never starts.

**Stop at any time:**
```bash
.venv/bin/prajna stage3 kill on --reason "<why>"      # checked before the run and between instruments
.venv/bin/prajna stage3 kill off
```

---

## 6. Safety checks that prevent accidental execution

1. **Two flags, both off by default** (`Field(default=False)`). Neither is in `.env`, and backfill needs both.
2. **Stage 1 is evaluated fresh at execution time.** A cached report is never trusted, so a later Stage 1 regression re-locks Stage 3.
3. **Stage 2 report** must be PASS, at most 7 days old, and include its test criterion P.
4. **Decisions must be APPROVED**, and the **registry must be consistent**.
5. **A write token is required** at the write path itself (`authorize_write`), supplied via the environment.
6. **The lock is checked twice:** in the CLI, and again inside `engine.run_snapshot` (defence in depth). Library callers cannot bypass it.
7. **The kill switch** (`var/run/stage3.kill`) is checked before the run and between instruments. It is audited (KILL_ON / KILL_OFF).
8. **Every refusal** lists each unmet condition, is recorded in `stage3_event` (append-only), exits with code 3, and writes nothing.
9. **`--commit` is mandatory** for `run` and `backfill`. Without it they exit 2, and `compute` is the read-only preview.
10. **Storage guards:** `feature_value` is append-only (a trigger) with `input_max_knowable_at < as_of` checked in the database. Inserts are idempotent (`on conflict do nothing`), and a disagreeing recompute fails the run instead of overwriting.
11. **Nothing is scheduled:** there is no cron entry.
12. **No vendor path:** `app.features` imports no vendor, network or fetch module (criterion J and a test), so Stage 3 cannot start the Stage 1 backfill.
13. **Tests cannot touch production:** the conftest guard refuses any non-test database.
