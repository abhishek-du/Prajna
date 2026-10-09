# Stage 4 dataset builder v3: report (2026-10-09, final)

**Research data only.**
- No model was trained.
- No order, signal or trading logic exists or was changed.
- Stage 1/2/3 logic, feature definitions, the D3 rule, cron, flags and order settings are untouched.
- No vendor call was made.
- Stage 3 criterion **E is PENDING**: full Stage 3 readiness is **not** claimed.

**Evidence:**
- `audit/evidence/stage4_dataset_v3.json`: the report, baselines, fingerprints and exports (`backend/ops/measure/stage4_v3_report.py`);
- `audit/evidence/stage4_dataset_v3_validation.json`: the independent validator (`backend/ops/measure/stage4_validate.py`).

**Plan:** `docs/STAGE4_DATASET_V3_PLAN.md`.

## What changed

| Item | Detail |
|---|---|
| Migration **0019** (additive; backup `prajna_20261009T1618_stage4_v3_pre_0019.dump`) | provenance columns on `training_dataset_run`; `flags` / `reason` / `run_id` on `training_label`; new `training_label_run`, `training_sample`, `training_split` (append-only) |
| Build contract (`app/training/policy.py`, `replay.py`, CLI) | v3 versions are pinned to **features-v4**; v1/v2 datasets and label-v1 are **frozen** (a build is refused); a version never mixes registry hashes; a dirty working tree is refused unless `--allow-dirty` (recorded) |
| label-v2 (`app/training/labels.py`) | label-v1 definitions; features-v4 price basis read at a **recorded knowledge cutoff**; explicit invalid rows; flags |
| Samples / splits (`samples.py`, `splits.py`) | eligibility, masks and exclusions recorded; expanding walk-forward with a 1-session embargo |
| Report / export (`ops/measure/stage4_v3_report.py`) | baselines (no ML), cost sensitivity, calibration interface, CSV.gz plus manifest |
| Tests | `backend/tests/training/test_v3.py` (14) |

## Schemas

**`training_feature_value`** (unchanged).
- One row per (dataset_version, session, snapshot, instrument, feature).
- Columns: `value`, `status` (VALID / MISSING_INPUT / STALE_INPUT / INVALID / NOT_APPLICABLE / NOT_AVAILABLE_HISTORICALLY), `reason`, `feature_version`, `inputs_sha256`.
- CHECK `input_max_knowable_at < as_of`.

**`training_label`, label-v2.** The nine label-v1 labels:

| Label | Definition |
|---|---|
| `ret_cc` | close(T) / close(T−1) − 1 |
| `gap` | open(T) / close(T−1) − 1 |
| `ret_oc` | close(T) / open(T) − 1 |
| `high_exc`, `low_exc` | high(T) / open(T) − 1, low(T) / open(T) − 1 |
| `hit_up_1/2`, `hit_dn_1/2` | threshold reach (±1%, ±2% from the open) |

- Window: T open → T close.
- `reason`: `BAR_REFUSED`, `MALFORMED_BAR`, `PREV_SESSION_MISSING`, `PREV_MALFORMED`.
- `flags`: `CA_EX_T:<ca_id>:<factor>`, `UNSUPPORTED_CA_EX_T:<type>`, `DIVIDEND_EX_T`, `EXTREME_UNEXPLAINED` (|ret_cc| or |gap| > 25% without an EXACT factor), `AMBIGUOUS_ORDER_1/_2`.
- The factor in `CA_EX_T` is rendered by `Decimal.normalize`, so 10 appears as `1E+1`. Kept as stored (changing it would break label-v2 determinism).

**`training_label_run`:** knowledge cutoff, registry, code sha, window, rows, `rows_sha256`, source fingerprints (bars, actions, factors, CA_ADJUSTMENT observations).

**`training_sample`:**
- Key: (dataset, label version, session, snapshot, instrument).
- Feature side: `core_valid` / `core_not_valid` (24 per-instrument baseline features), `feature_eligible`.
- Label side: `labels_valid`, `label_flags`.
- `masks`: `CA_WINDOW` (a non-dividend action with T − ex ∈ [−1, 5] sessions), `EXTREME_UNEXPLAINED`, `AMBIGUOUS_ORDER_*`.
- `exclusion_reasons`: `NO_LABEL`, `LABEL_<reason>`, `CORE_FEATURE_NOT_VALID`.
- CHECKs: `eligible` ⇔ no exclusion; `label_start_at > as_of`.
- The six market-context baseline features are per snapshot. They are exported separately and never exclude an instrument.

**`training_split`:** scheme `wf-exp-120-20-20-e1`.
- Expanding TRAIN ≥ 120 sessions, 1 embargo session, VALID 20, 1 embargo, TEST 20, roll 20.
- The session boundaries are identical for every instrument.

## Builds

| | stage4-ds-v3-strict | stage4-ds-v3-asif |
|---|---|---|
| Knowability | STRICT_PIT-v2 (`train_strict`: corporate actions as observed) | AS_IF_LIVE-v2 (`train_asif2`: measured live lags; **ASSUMED**, research only) |
| Registry | features-v4 `6f998a76c49462c3244b5eecb2d783e75c6fff9d26365ae3540c8e88dbb201c3` | same |
| Code | `1f07d52` | `1f07d52` |
| Snapshots | PRE_SESSION + PRE_OPEN, 2026-09-24 → 10-09: 22 | PRE_SESSION, 2025-09-24 → 2026-10-09: 257 |
| Feature rows | **4,655,286** (md5 `62e70a81…`) | **47,480,669** (md5 `acc65124…`) |
| Status | VALID 3,030,266; MISSING 907,985; NOT_AVAILABLE_HIST. 371,576; STALE 254,306; INVALID 91,153 | VALID 17,942,936; MISSING 9,891,134; NOT_AVAILABLE_HIST. 18,942,954; STALE 658,163; INVALID 45,482 |
| Samples (label-v2) | 77,510 (38,755 per snapshot type); **eligible 55,956** | 817,715; **eligible 566,209** |
| Exclusions | CORE_FEATURE_NOT_VALID 14,376; NO_LABEL 9,296 | CORE_FEATURE_NOT_VALID 240,635; NO_LABEL 28,967; LABEL_BAR_REFUSED 373 |
| Masks among eligible (per type) | AMBIGUOUS_ORDER_1 8,126; _2 2,487; CA_WINDOW 25; EXTREME 2 | AMBIGUOUS_ORDER_1 160,302; _2 48,705; CA_WINDOW 598; EXTREME 16 |
| Class balance, eligible (hit_up_1 / hit_dn_1 / hit_up_2 / hit_dn_2) | 0.497 / 0.701 / 0.310 / 0.480 | 0.543 / 0.638 / 0.346 / 0.411 |
| Walk-forward folds | **none**: 11 sessions < 162 (recorded) | **5** (TEST blocks 2026-04-27 → 2026-09-17) |
| Sample fingerprint | `3651ab76…` (recomputed: match) | `62b67e84…` (recomputed: match) |

`NO_LABEL` is mostly 2026-10-09: its daily bar is fetched the next morning.

**label-v2:**
- Run `5f20b363-0729-4817-9759-7eb14369fb07`, cutoff **2026-10-09 16:35:10 IST**.
- 7,113,528 rows; 3,571 instruments; 2025-09-24 → 2026-10-08.
- `rows_sha256` `f277f36c…` (recomputed from the stored rows: **match**).
- BAR_REFUSED 3,357 rows; PREV_SESSION_MISSING 31,616.
- **BLSE 2026-10-06 `ret_cc` = +0.83%** (`CA_EX_T:4096:2`); it was −49.6% in label-v1.

**Exports** (`backend/var/stage4/exports/`, not in git; sha256 in `manifest.json`):

| File | Rows | sha256 |
|---|---|---|
| strict `PRE_SESSION.csv.gz` | 38,755 | `9e8c645b…` |
| strict `PRE_OPEN.csv.gz` | 38,755 | `43745e07…` |
| asif `PRE_SESSION.csv.gz` | 817,715 | `b289815c…` |

Missing values are empty cells plus a `*__status` column, never 0.

## Integrity (independent validator)

| Check | strict v3 | asif v3 | Result |
|---|---|---|---|
| Duplicates / duplicate snapshots / orphans / NaN-inf / value-status inconsistency | 0 / 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 / 0 | **PASS** |
| `input_max_knowable_at ≥ as_of` | 0 | 0 | **PASS** |
| Non-trading dates / future timestamps / registry mismatch | 0 / 0 / 0 | 0 / 0 / 0 | **PASS** |
| Missing calendar snapshots / `as_of` ≠ calendar | 0 / 0 | 0 / 0 | **PASS** |
| label-v2 leakage (`label_start_at ≤ as_of`), 17,753,958 pairs | 0 | | **PASS** |
| Fresh read-only recompute (10 snapshots × 10 instruments each) | 6,260 rows, 0 mismatches | 6,060 rows, 0 mismatches | **PASS** |
| Raw SQL (`ret_1d` / `sma_20` / `avg_volume_20`; label `ret_cc`) | 270 + 200, 0 mismatches | 296 + 200, 0 mismatches | **PASS** |
| News never 0 before collection | 0 of 196,606 + 13,996 | 0 of 5,558,839 + 1,566,328 | **PASS** |
| Late bars never used before knowable | 20 of 20 | | **PASS** |
| STRICT v3 vs production `feature_value` | 10-08: values differ only for BLSE (the F3 fix; production holds features-v2); 09-29: only `sector_rs_20` (known finding) | | **EXPLAINED** |
| CA "announced earlier, stored later" scenarios | vacuous: since CA-OBSERVED no view carries announcement knowability, so 0 cases | | **NOT RUN** (covered by `tests/stage2/test_ca_observed.py`) |

## Determinism and idempotency

| Check | Result |
|---|---|
| STRICT v3 build rerun | 22 of 22 snapshots skipped — **PASS** |
| AS_IF_LIVE v3 build rerun | 257 of 257 snapshots skipped — **PASS** |
| STRICT / AS_IF_LIVE samples rerun | 0 inserted; `build_sha256` `3651ab76…` / `62b67e84…` unchanged — **PASS** |
| label-v2 rerun at the recorded cutoff (run `ad51acbe-2ba2-4ed6-8e4c-b1c6916516fe`, code `507d0ec`) | 0 inserted, drift 0, `rows_sha256` `f277f36c…` and source fingerprints (md5 `64dea26c…`) identical to run `5f20b363` (code `1f07d52`) — **PASS** |
| Sample and label fingerprints recomputed from the stored rows | match — **PASS** |
| Frozen data, before = after the v3 work | **PASS**: v1/v2 per-session fingerprints (e.g. v2-asif 47,274,794 `e7d3a893…`, v2-strict 4,229,340 `7161a1b4…`); label-v1 7,077,591 `15f0cb45…`; `feature_value` 801,434 `b45381f3…`; 26 frozen runs `acf24bec…` |
| Frozen-version refusal (production CLI) | `prajna training labels` → "REFUSED: label-v1 is frozen"; a dirty-tree build → refused — **PASS** |
| Crontab / flags | sha `dbc5b41b…`; `PRAJNA_STAGE3_ENABLED=true`, `PRAJNA_STAGE3_BACKFILL_ENABLED=false` (unchanged) |

## Baselines (NOT a model; no profitability claim)

AS_IF_LIVE v3, PRE_SESSION, target `ret_oc`, eligible samples, per walk-forward TEST block. Rank IC is the session cross-sectional Spearman (mean, t). Long-short is the top minus bottom decile, net of c bps per leg round trip (2c per session).

| Predictor | Masked? | Rank IC by fold (mean) | Sign hit | L/S gross per session | L/S net 20 bps |
|---|---|---|---|---|---|
| reversal −`ret_1d` | unmasked | 0.036 / 0.041 / 0.034 / 0.053 / 0.046 (t 3.0–10.4) | 0.50–0.53 | +0.24% to +0.32% | −0.08% to −0.16% |
| reversal −`ret_1d` | masked | 0.045 / 0.056 / 0.047 / 0.072 / 0.055 | 0.50–0.53 | +0.33% to +0.48% | −0.07% to +0.08% |
| momentum `ret_5d` | unmasked | −0.042 … −0.027 | 0.49–0.51 | −0.25% to −0.38% | −0.65% to −0.78% |
| zero | | MAE 0.0171–0.0192 | | | |

**Caveats:**
- These are heuristics evaluated on AS_IF_LIVE (assumed knowability), with survivorship bias.
- The open price may not be executable; microstructure effects (bid-ask bounce, illiquid small caps) are not controlled.
- The costs are illustrative; the Upstox/NSE fee schedule is not asserted.
- **No model quality or profitability is implied.**

**Calibration interface demo.** The TRAIN base rate of `hit_up_1` (0.535–0.561) used as a constant probability on TEST gives Brier 0.246–0.252. This is the reference any probabilistic model must beat.

## Survivorship and universe

- The universe per session grows from 2,939 (2025-09-24) to 3,549 (2026-10-09).
- Only instruments in today's Upstox master exist; companies delisted before 2026-09-23 were never downloaded. This is a **survivorship bias**, not repairable from Prajna's data.
- 21 REMOVED_FROM_MASTER names are present.
- Fundamentals, sector, news and pre-open exist only from 2026-09-24 / 09-29. They are NOT_AVAILABLE_HISTORICALLY in AS_IF_LIVE, never 0.

## Unresolved decisions (not implemented; for your approval)

**A target/stop ("first touch") label is not defined anywhere.** Each choice changes the research question:

1. **Horizon.**
   - (a) one session (T open → T close): consistent with label-v2, needs a 1-session embargo;
   - (b) N sessions: more events, but needs a purge/embargo of N, and overnight gaps can jump the stop.
2. **Entry.**
   - (a) T open: the vendor open, maybe not executable;
   - (b) PRE_OPEN IEP: only from 2026-09-24, so the PRE_OPEN dataset only;
   - (c) first-minute VWAP: 1-minute bars only from 2026-09-23.
3. **Levels.**
   - (a) fixed ±x%: simple, ignores volatility;
   - (b) ATR multiples: uses `atr_pct_14` (VALID from about 2025-10-16).
4. **Both touched the same day:** 8.1–21% of sessions (AMBIGUOUS_ORDER_2 / _1).
   - (a) exclude;
   - (b) pessimistic: stop first;
   - (c) resolve with 1-minute bars: only about 12 sessions are possible today.
5. **Exit if neither is touched:** the close of the horizon.
6. **Costs:** brokerage, STT, exchange, SEBI, stamp and GST per side, plus slippage. They must be specified before net labels.

**Also open:**
- Whether PRE_OPEN models use the PRE_OPEN `gap` (visible at 09:08 through the pre-open book) — a leakage-sensitive choice.
- The liquidity floor for the research universe.
