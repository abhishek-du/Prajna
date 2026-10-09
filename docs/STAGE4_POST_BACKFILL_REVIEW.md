# Stage 4 post-backfill review: KN-CA, feature usability, model readiness

**Read-only review, 2026-10-09.**
- Evidence: `audit/evidence/stage4_post_backfill_review.json`, produced by `backend/ops/measure/stage4_review.py` in one READ ONLY transaction per section.
- Nothing in the database, Stage 3, cron, flags or canonical data was changed.
- No model was trained and no signal, risk or order code exists.
- Labels: **VERIFIED** = measured or shown by SQL or code in this review; **INFERRED** = follows from verified facts but was not observed directly; **UNKNOWN** = cannot be determined from Prajna's data.

## Verdict

| | Result | Why |
|---|---|---|
| DATASET_INTEGRITY | **PASS**, with three data-quality findings (F3, F4, F5) | v2: 0 duplicates, 0 PIT violations, 0 label leakage, every calendar snapshot present, one registry hash, frozen policy parameters, replays exact. Not structural failures: corporate events missing from the vendor feed (F4) and one price-basis error (F3, BLSE) put wrong values into a small, identifiable set of rows. |
| KN_CA_LIVE_IMPACT | **PASS** (as observed) | 0 of the 4 committed production snapshots consumed a corporate action fetched after its `as_of` (VERIFIED). The mechanism exists (F1): a run that starts after `as_of` sees actions stored in between. Late and manual runs are exposed; it never happened in the measured history. |
| MODEL_READINESS | **READY_FOR_RESEARCH** | AS_IF_LIVE-v2 supports a price/volume/index/global baseline for about 230 sessions (2025-11 → 2026-10), with explicit masks for F3/F4 rows. STRICT is a forward hold-out of only 9 labelled sessions. No production target is chosen. |
| PRODUCTION_CHANGED | **NO** | `feature_value` 801,434 rows, md5 `b45381f3…` = baseline; crontab sha `dbc5b41b…` = baseline; `PRAJNA_STAGE3_ENABLED=true`, `PRAJNA_STAGE3_BACKFILL_ENABLED=false`; registry `features-v2`, 104, `dd696ca6…`; alembic 0017. |

**Correction to my earlier summary.** I reported "96/104 features historically backfillable" for AS_IF_LIVE. That number counted every feature with *any* VALID row.
- Fundamentals, sector, legacy news and multi-source news have values only in the last 6–9 of 256 sessions.
- Under the usable-coverage rule in §2 (≥ 80% VALID from a session onward), **34 features** are usable for at least the last 6 months of the AS_IF_LIVE window. **30** of them are usable from 2025-12-23, which excludes FII/DII.

## Findings

| # | Severity | Finding | Status |
|---|---|---|---|
| F1 | MEDIUM | KN-CA backdates corporate-action knowability. Live runs are exposed only between `as_of` and the run start; recomputes and backfills are fully exposed | VERIFIED |
| F2 | MEDIUM | `pit.bars_adjusted` reads the corporate-action horizon (`min(ex_date)`) un-time-filtered | VERIFIED code; impact INFERRED |
| F3 | HIGH | BLSE 1:2 split (ex 2026-10-06): the pre-ex bars are stored unadjusted but treated as vendor-adjusted, leaving a false −50% in the adjusted series. Affects **production** `feature_value` 2026-10-08, AS_IF_LIVE rows and labels | VERIFIED |
| F4 | HIGH (for labels) | Events absent from the vendor CA feed (probably demergers, e.g. VEDL 2026-04-30, TMPV 2025-10-14) and RIGHTS (UNSUPPORTED) leave unadjusted jumps in features and labels: 29 `ret_cc` labels beyond ±25% | VERIFIED values; event type INFERRED |
| F5 | MEDIUM | `pat_yoy_q` / `revenue_yoy_q` are INVALID (MALFORMED_INPUT) for 61% / 55% of STRICT rows, inherited from production | VERIFIED |
| F6 | LOW | The generated dataset report has section headings saying "STRICT_PIT" / "AS_IF_LIVE-v1" while the data is v2 | VERIFIED |
| F7 | LOW | `sector_rs_20` peers come from today's lifecycle list (reported before) | VERIFIED |
| F8 | OPERATIONAL | Today's (2026-10-09) scheduled Stage 3 runs were REFUSED: Stage 1 F failed on MOLDTECH / MOLDTKPAC, whose bonus was vendor-adjusted before the action reached Prajna. Awaiting your decision (previous message) | VERIFIED |

## 1. Corporate-action knowability (KN-CA)

### The path (VERIFIED, code)

1. **Ingest** (`app/ingest/corporate_actions.py:181`): each event gets `knowable_at` from `contracts/knowable.for_announcement_date` (`app/contracts/knowable.py:188-202`).
   - It returns the END of the announcement date (23:59:59.999 IST) whenever that is before `fetched_at`; otherwise `fetched_at`.
   - So `knowable_at ≤ fetched_at` always.
2. **Measured on the 2,336 stored actions:** `knowable_at < fetched_at` for **all 2,336**. The lag is min 5 d 16 h, median 134 d, max 644 d.
3. **Upstox lists an action around its ex-date** (fetches by day in the evidence). For example, the 2026-10-03 weekly fetch returned ex-dates from 09-22 to 10-01 that were announced as early as May.
4. **Factors** (`app/ingest/ca_derive.py:118,155`): `ca_factor.knowable_at` is the action's KN-CA `knowable_at` (2,336 of 2,336 equal). Every factor was derived after the fetch, at 06:xx IST maintenance.
5. **Stage 2 PIT read:**
   - `pit.corporate_actions` filters `canon_corporate_action.knowable_at < as_of` (`app/canon/pit.py:141`).
   - `pit.bars_adjusted` applies EXACT factors with `ex_date ≤ day` and `knowable_at < as_of` (`pit.py:98-102`).
   - Neither checks `fetched_at`.
6. **Stage 3:**
   - `features/inputs.instrument_inputs` → `pit.bars_adjusted` (`inputs.py:93`) gives every price and volume feature; `pit.corporate_actions` (`inputs.py:101`) gives the 8 `ca_days_*` features.
   - `inputs_sha256` hashes (`id, action_type, ex_date, knowable_at`).
   - `engine.run_snapshot` reads everything in ONE REPEATABLE READ snapshot taken when the run starts (`engine.py:428`), not at `as_of`.
7. **Recompute / backfill:**
   - `prajna stage3 run|backfill` → `engine.run_snapshot` (`cli/main.py:1491`) reads the same views.
   - `persist` raises `DeterminismMismatch` if a recompute differs from a stored row (`engine.py:409`). Stored rows are protected; never-stored sessions are not.

### A. Can a live snapshot consume an action before Prajna observed it?

**Not before it is stored** (VERIFIED): a row cannot be read before it exists.

**But after `as_of` and before the run starts: YES** (VERIFIED mechanism). KN-CA dates the row earlier than `as_of`, and the run's snapshot starts later.

Measured on every production Stage 3 run (`ingest_run`, source PRAJNA_STAGE3):

| Session | Snapshot | Run started after as_of | Actions fetched in (as_of, run start) |
|---|---|---|---|
| 2026-09-29 | PRE_SESSION | 95–398 min (4 runs) | **0** |
| 2026-09-29 | PRE_OPEN | 92–317 min (2 runs) | **0** |
| 2026-10-08 | PRE_SESSION | 579–600 min (3 runs) | **0** |
| 2026-10-08 | PRE_OPEN | 585 min | **0** |

**All 4 committed production snapshots were written by late runs, and none consumed a late action** (VERIFIED). Exposure in the future (INFERRED):

| Run type | Window | Actions stored in it so far |
|---|---|---|
| Scheduled PRE_SESSION | 31 s | 0 |
| Scheduled PRE_OPEN | as_of 09:08 to run 09:22–09:33 | 0 |
| Late or manual runs | as_of until the run starts | none in the history |

Live action fetches happened at 06:30 IST (daily refresh) and between 10:30 and 12:31 IST (Saturday weekly run; Monday 2026-09-28 10:45 once). A late weekday run after 10:45 *would* have consumed the 09-28 BONUS of INE2FMX01012 (ex 09-28, announced 07-23, fetched 09-28 10:45).

### B. Can recomputing an old snapshot today change its features?

**YES** (VERIFIED, reproducible). Dataset v1 is exactly that recompute: production views, rebuilt on 2026-10-08. Compared with the observed-time v2 on the same sessions:

- **STRICT, 10 sessions:**
  - **56,066 `ca_days_*` values or statuses differ.**
  - 2026-09-24: 27,992 rows per snapshot (3,499 instruments). All CAs were fetched at 14:52–16:24 that day, after the 08:59:59 `as_of`.
  - 09-25 → 10-01: 11–15 rows per snapshot (6–8 instruments).
  - Examples:
    - ARIHANTACA (BONUS ex 10-01, announced 08-13, fetched 10-03): `ca_days_to_bonus` was 6 on 09-25 in the recompute; Prajna knew nothing until 10-03.
    - LOTUSDEV (dividend ex 09-25, fetched 09-26): `ca_days_since_dividend` was 0 on 09-25 instead of 14 (the earlier, observed dividend).
    - SAIL and IGL: `ca_days_to_dividend` 5 and 6 → MISSING.
  - Price features: in STRICT only their `inputs_sha256` differ (230 rows), not their values.
- **AS_IF_LIVE, 54 common sessions:**
  - 8,858–11,184 rows per `ca_days_*` feature differ.
  - **6,418 price/volume rows** go VALID → MISSING_INPUT, on 27 instruments, all with a SPLIT or BONUS.
  - The cause: in the recompute a factor known only from its announcement adjusted the bars; without it, `bars_adjusted` refuses the vendor-adjusted rows as RECONSTRUCTED.
  - So KN-CA also moves **price** features, not only the event features.
- **Production rows** (`feature_value`, 2026-09-29 and 10-08) were not changed. A recompute of them differs only in `ca_days_*` `inputs_sha256` (24,736 and 24,784 rows); the values are identical.

### C. Affected features, dates, instruments

**Features:**
- The 8 `ca_days_*` features, directly.
- Every bar-based feature (price_technical 23, volume_liquidity 3, `sector_rs_20`, `preopen_gap_pct`, `preopen_ieq_to_avg_volume`) through `ca_factor`, for instruments with a SPLIT or BONUS. EXACT factors: 143 of 2,336 actions; the rest are dividends, rights and other types with no price factor.

**Dates:** any snapshot whose `as_of` lies between an action's announcement-EOD and its `fetched_at`.
- Live-collected actions: from 2026-09-24 (bulk load day) and the windows of the 16 actions stored later (evidence `kn_ca.fetch_vs_ex_date`).
- Historical recomputes of anything before 2026-09-24: every one.

**Instruments:**
- 3,499 on 2026-09-24 (STRICT recompute).
- 6–8 per later session.
- 27 split/bonus instruments for price features (AS_IF_LIVE recompute).

### D. Does migration 0017 isolate the semantics?

**STRICT_PIT-v2 (VERIFIED):**
- `train_strict.canon_corporate_action.knowable_at = greatest(knowable_at, fetched_at)` for 2,336 of 2,336 rows.
- `train_strict.ca_factor.knowable_at = greatest(f.knowable_at, action.fetched_at)` for 2,336 of 2,336.
- The engine reaches both only by unqualified name inside the replay transaction.
- Scenario check: 44 STRICT rows lie between an action's announcement and its storage; 0 of them reflect the unobserved action.

**AS_IF_LIVE-v2 (VERIFIED):**
- 2,336 of 2,336 rows match `least(observed, greatest(KN-CA, ex_date + 297,180 s))`.
- 0 rows earlier than KN-CA; 0 later than the fetch.
- Factor and action knowability are equal for 2,336 of 2,336.
- All 7 runs carry one identical `policy_params` and one registry hash. The parameters are frozen: 17 rows, one `measured_at`, append-only.

**Gap (F2, VERIFIED code):** `bars_adjusted` reads `select min(ex_date) from corporate_action` unqualified and without a time filter (`pit.py:101`).
- Today's horizon is 2025-09-24, from actions first stored 2026-09-24 09:22 UTC, and it applies to every historical `as_of`.
- Today this is conservative: it refuses more bars, never fewer.
- But a future download reaching further back would move the horizon and change any recompute (INFERRED). It is not isolated by 0017.

### E. Downstream consumers still on KN-CA (VERIFIED, grep)

| Consumer | Uses KN-CA for | Decision impact |
|---|---|---|
| `canon/pit.py` (`corporate_actions`, `bars_adjusted`) | Stage 3 live, `stage3 run/backfill`, Stage 2 probes | yes |
| `ingest/ca_derive.py` | copies KN-CA into `ca_factor` | yes (via pit) |
| `acceptance/stage2.py`, `acceptance/stage3.py` | PIT probes; factor horizon check | gate evidence |
| `canon/quality.py` (`knowable_at > fetched_at` check) | quality report | none |
| `ingest/candles.py` + `contracts/revision.py` | CA_ADJUSTMENT classification uses recorded events, not `knowable_at` | none |
| `readapi/main.py`, `web/viewer.py`, `api/*` | display | none |
| Stage 4 training v2 | **not** KN-CA (0017 views) | none |

### Proposed fix (not implemented; needs your approval)

**Rule.** For decisions, a corporate action is knowable at `greatest(KN-CA, fetched_at)`. Keep the announcement date as metadata.

**Minimal change:**
1. Additive migration:
   - Re-create the `canon_corporate_action` view with `knowable_at = greatest(knowable_at, fetched_at)` and `knowable_at_basis` stating it.
   - Add `canon_ca_factor` (`greatest(f.knowable_at, c.fetched_at)`).
   - No stored row changes. `corporate_action.knowable_at` keeps the KN-CA value for audit.
2. `pit.bars_adjusted` reads `canon_ca_factor`. Its horizon becomes `min(ex_date)` over actions with `greatest(knowable, fetched) < as_of`, which fixes F2.
3. Contract docstring: KN-CA becomes "announcement evidence, not knowability".

**Compatibility:**
- Live scheduled runs: unchanged values (0 exposures measured).
- Stored `feature_value` 09-29 / 10-08: a recompute would now raise `DeterminismMismatch` on the `ca_days_*` rows, because their `inputs_sha256` change.
  - Either bump `feature_version` of the 8 `ca_days_*` and of the factor-dependent features (registry `features-v3`, new hash, effective from a session boundary),
  - or record the old snapshots as KN-CA-era and never recompute them.
  - I recommend the version bump.
- Stage 2 gate probes must be re-run.

**Regression tests:**
- An action stored after `as_of` but announced before is invisible to `pit.corporate_actions` and `pit.bars_adjusted`.
- A run starting after an action's fetch excludes it for an earlier `as_of`.
- The horizon ignores actions stored after `as_of`.
- STRICT v2 and the fixed production view agree row for row.
- The existing KN-CA tests are rewritten, not deleted.

**Fix for F3 (BLSE), separate and also awaiting approval:**
- `vendor_applied=APPLIED` is evidence from *later* observations; the stored pre-ex bars were fetched before the vendor adjusted them (prev close 319.15 / ex open 163.7 ≈ 2).
- `bars_adjusted` must decide "baked" per payload: a factor is baked only if that payload was fetched after the first CA_ADJUSTMENT observation of the factor. Otherwise it is applied.
- Test: BLSE 10-05 bar must adjust to 159.6.
- **Production 2026-10-08 values for BLSE are wrong** (`ret_5d` −0.507, `close_to_sma_20` −0.479, `volatility_20` 2.44). They stay stored (append-only). Correcting them needs a feature-version decision, as above.

## 2. Dataset readiness for modelling

Source: the full v2 tables. Per-feature, per-snapshot status counts are in evidence `readiness.<dataset>.feature_status`; monthly family coverage is in `family_valid_share_by_month`.

### Coverage by family: AS_IF_LIVE-v2, PRE_SESSION, VALID share of applicable rows

| Family | 2025-10 | 2025-11 | 2026-01 | 2026-04 | 2026-07 | 2026-10 |
|---|---|---|---|---|---|---|
| Stock bars (price, volume) | 0.25 | 0.72 | 0.86 | 0.86 | 0.90 | 0.93 |
| Global | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| FII/DII | 0 (n/a) | 0 | 0 | 0.85 | 1.00 | 1.00 |
| Corporate actions | 0.002 | 0.011 | 0.020 | 0.036 | 0.054 | 0.11 |
| Fundamentals, sector, news | 0 (NOT_AVAILABLE) | 0 | 0 | 0 | 0 | 0.66–0.90 (last 6–9 sessions) |

Index and VIX context is VALID from 2025-09-24, because index bars go back to 2020.

**First session with ≥ 80% VALID from then on, AS_IF_LIVE** (`first_session_valid_ge_80pct_thereafter`):

| From | Features |
|---|---|
| 2025-09-24 | index × 3, VIX × 2, global |
| 2025-09-26 – 2025-10-27 | `ret_1d`, `ret_5d` (10-03), `ema_12` (10-13), `atr_14` / `atr_pct_14` / `rsi_14` (10-16), 20-session family (10-24 to 10-27) |
| 2025-11 | `ema_26`, `macd_*` (11-03 / 11-14) |
| 2025-12 | `sma_50`, `close_to_sma_50` (12-08), `beta_60` (12-23) |
| 2026-04-02 / 04-09 | FII/DII |
| never | `sma_200`, `close_to_sma_200` (need ~200 sessions after the 2025-09-24 horizon); all 8 `ca_days_*`; `eps_yoy`, `pat_yoy`, `revenue_yoy`, `*_q`, `liabilities_to_assets`, `pe_to_sector`; `news_hours_since_last`; `mnews_company_time_since_last_s` |
| only from 2026-09-25 / 09-30 | everything else (fundamentals, legacy and multi-source news) |

**Per symbol** (8 core price features): median 94% VALID, p10 61%. 203 of 3,566 symbols are below 50%: new listings and illiquid or suspended names. 7 symbols have 0%.

**Universe** grows from 2,939 (2025-09-24) to 3,545 (2026-10-08): survivorship plus new listings, 620 of which list after 2025-09-24.

**PRE_SESSION vs PRE_OPEN** (STRICT, same session and instrument):
- Only PRE_OPEN has the 4 `preopen_*` features (35,239 rows each).
- Identical for every price, volume, index and global feature.
- They differ only where inputs can arrive between 08:59:59 and 09:08:
  - multi-source news (5,286 `mnews_company_time_since_last_s`, small counts elsewhere);
  - `sector_rs_20` (1,894), `news_hours_since_last` (1,698);
  - fundamentals (84–117 rows per feature): fundamentals were refreshed in that window on 2026-09-25.
- So **the two snapshots are different schemas**. A model must be trained per snapshot type, never on a pooled set.

**Malformed values:**
- `pat_yoy_q` / `revenue_yoy_q` (F5): exclude.
- `roe_pct` / `roce_pct`: < 0.05% INVALID.
- Value extremes in AS_IF_LIVE (`value_outliers_core`): `ret_1d` −86% … +50%, `volume_spike_20` up to 7,525, `volatility_20` up to 6.98. The tails include F3/F4 artefacts. Winsorise or robust-scale them, and **mask** them as below.

### Recommended baseline (research)

**Dataset:**
- AS_IF_LIVE-v2, PRE_SESSION, sessions **2025-12-23 → 2026-10-07** (beta_60 stable, about 195 sessions).
- 2025-11-03 → 2025-12-22 can be added if `sma_50` / `beta_60` are dropped.

**Features (30 feature ids):**
- `ret_1d`, `ret_5d`, `ret_20d`;
- `sma_20`, `sma_50`, `close_to_sma_20`, `close_to_sma_50`;
- `ema_12`, `ema_26`, `macd_line`, `macd_trigger`, `macd_histogram`;
- `rsi_14`, `atr_14`, `atr_pct_14`, `volatility_20`, `beta_60`;
- `dist_high_20`, `dist_low_20`, `breakout_20`, `breakdown_20`;
- `avg_volume_20`, `volume_spike_20`, `turnover_20`;
- `index_ret_1d` / `_5d` / `close_to_sma_50` (Nifty 50 and Nifty Bank), `india_vix_level`, `india_vix_change_5d`, `global_ret_1d` (13 series).

Level features (`sma_*`, `ema_*`, `atr_14`, `avg_volume_20`, `turnover_20`) are price- or size-scaled: use their ratio forms, or normalise per symbol.

**Optional, added later and ablated:**
- FII/DII (from 2026-04-09: halves the window).
- `ca_days_since_*` (sparse; see the missingness rules).

**Exclude initially:**
- `sma_200` / `close_to_sma_200`, `ca_days_to_*`;
- fundamentals (9 sessions), `sector_rs_20`;
- legacy news, multi-source news (6 sessions), pre-open (STRICT only);
- `pat_yoy_q`, `revenue_yoy_q`.

### Missingness rules (never zero-fill)

1. **NOT_AVAILABLE_HISTORICALLY:** exclude the *feature* for that window. Never impute.
2. **MISSING_INPUT / STALE_INPUT on a baseline feature:** exclude the *row* from training, or use a model that handles missing values natively, with an explicit missing-indicator. Count and report the exclusions per session and per symbol.
3. **`ca_days_*` MISSING:** means "no corporate action known in the horizon". If ever used, encode it as a separate indicator plus a capped value, documented as such.
4. **INVALID:** exclude the feature (F5) or the row; never repair.
5. **Event mask, logged, not silent deletion:**
   - Mark `(instrument, session)` pairs within [ex − 1, ex + 5] of any stored corporate action.
   - Mark any `|ret_cc|`, `|gap|` > 25% without a known factor (F4: 29 `ret_cc` rows).
   - Mark BLSE from 2026-10-06 (F3).
   - Train with and without the mask and report both.
6. **Universe:** a session's training universe is its replay universe (`training_session_done`), never today's list. Report the symbol count per session.

### Prediction-time snapshot contract (for future training and serving)

1. One row is (snapshot type, session T, instrument), from `training_feature_value` / `feature_value` at `as_of(T, kind)` from the calendar:
   - PRE_SESSION: pre-open start − 1 s;
   - PRE_OPEN: pre-open start + 8 min.
2. **Inputs:** every input has `input_max_knowable_at < as_of` (DB CHECK). Bar features use sessions < T only.
3. **Same registry hash and feature versions** at training and serving. A model trained on AS_IF_LIVE must be re-validated on STRICT / live rows before any use.
4. **Status travels with the value.** A serving row whose status differs from VALID gets the same rule as in training, never a default.
5. The label for T starts at T's open (`label_start_at`), strictly after both `as_of`s.

## 3. Labels and evaluation design

**`label-v1`:**
- 9 labels × 786,399 rows each.
- Sessions 2025-09-24 → 2026-10-07; 10-08 is pending that bar.
- `ret_cc` and `gap` are MISSING on 15,753 rows (no previous session bar); the others are 100% VALID.

Means are about 0 for `ret_cc`, −0.25% for `ret_oc`. Hit rates: up-1% 53%, down-1% 62%, up-2% 33%, down-2% 40%.

**Candidate targets** (no target chosen without a research question):

| Research question | Target | Horizon | Notes |
|---|---|---|---|
| Does the pre-session state rank tomorrow's open-to-close move? | `ret_oc`, or its cross-sectional rank | T open → T close | tradable entry at the open; excludes the gap |
| Is the overnight gap predictable from pre-session information? | `gap` | close T−1 → open T | needs PRE_OPEN context; the gap is visible at 09:08 in the pre-open book, so a PRE_OPEN model would be near-trivially informed |
| Volatility or range regime | `high_exc − low_exc`, ATR-normalised | T | robust to direction; useful for sizing research |
| Threshold reach | `hit_up_x` / `hit_dn_x` | T | **not** a target/stop label (see below) |
| Multi-day | needs a new label version (e.g. 5-session return) | T → T+4 | requires purging (below) |

**Why daily OHLC cannot order the target and the stop.** A daily bar holds only open, high, low and close. Whether the high came before the low inside T is not recorded.
- In label-v1, **64,042 of 786,399 rows (8.1%)** hit both +2% and −2% on the same day.
- For those rows a "take-profit +2% / stop −2%" outcome is undetermined; any rule (stop first, target first, close) is an assumption.
- Prajna's 1-minute bars start only on 2026-09-23 (the intraday history download is DEFERRED). So the order cannot be resolved historically.
- A target/stop label needs 1-minute data (forward only, or the deferred backfill) or an explicitly pessimistic convention (stop first), reported as such.

**Walk-forward evaluation:**
1. **Chronological folds, expanding window.** For example:
   - train ≥ 120 sessions;
   - validation the next 20 sessions (tuning only);
   - test the next 20 sessions;
   - roll by 20.
   - Boundaries are session dates, the same for every symbol.
2. **Purge and embargo.**
   - label-v1 spans one session (T open → T close), and features at T+1 use bar T.
   - A training sample's label therefore ends before any later test sample's `as_of`. With a 1-session label, an **embargo of 1 session** between train and test end is sufficient.
   - Multi-day labels of h sessions need a purge of h sessions before each test block and an embargo of h after it.
   - Features with long lookbacks (`beta_60`, `sma_50`) overlap across folds legitimately; they are inputs, not labels.
3. **Data regime split.** Tune on AS_IF_LIVE. The final out-of-sample check is on STRICT and live sessions accumulating from 2026-09-24, and it is reported separately. AS_IF_LIVE results are ASSUMED-knowability research and must not be presented as live performance.
4. **Baselines:**
   - zero / mean prediction;
   - previous-day return (momentum and reversal sign);
   - a sector-free cross-sectional rank of `ret_5d`;
   - logistic or linear regression on the baseline set.
   - A model is interesting only if it beats these out of sample.
5. **Universe and missing-data controls:**
   - fixed universe rules per session (replay universe, liquidity floor e.g. `turnover_20` above a stated quantile, stated before testing);
   - report results with and without the event mask, and per liquidity bucket;
   - report rows excluded by missingness.
6. **Metrics:**
   - Classification: log-loss, Brier, calibration curve and ECE, AUC, precision at k.
   - Regression or ranking: rank IC (Spearman) by session with mean, t-stat and hit rate; MAE.
   - Portfolio simulation of the top-k / bottom-k per session: gross and **net** returns, turnover, max drawdown, Sharpe with a stated annualisation, all per fold.
7. **Transaction-cost sensitivity.** Evaluate at 0 / 10 / 20 / 40 bps round trip, plus a slippage scenario for low-turnover names. The current Upstox/NSE fee schedule (brokerage, STT, exchange, SEBI, stamp, GST) must be verified and parameterised before net results are quoted; it is not asserted here.

## 4. Integrity and operational safety

**VERIFIED:**
- alembic `0017`.
- v2 runs COMPLETE: STRICT 5 runs (20 snapshots, 4,229,340 rows, 1 idempotency run with 0 snapshots); AS_IF_LIVE 7 runs (256 snapshots, 47,274,794 rows).
- v1 runs (14) SUPERSEDED with their rows kept: 9,359,212 + 4,229,340 + 28,599 pilot.
- One registry hash across all runs, `dd696ca6…`.
- Done markers equal the row counts.
- `feature_value` = baseline; crontab = baseline (Stage 3 lines at 09:00:30 and 09:22); flags unchanged.
- `stage3_event` 35–36: today's REFUSED runs (F8).

**Report inconsistencies (F6):**
- In `docs/STAGE4_TRAINING_DATASET_REPORT.md`, the headings "Historical windows per family → STRICT_PIT / AS_IF_LIVE-v1" and "Feature coverage: STRICT_PIT / AS_IF_LIVE-v1" are hard-coded in `ops/measure/stage4_report.py`. The data under them is **v2**.
- The `class` column ("PARTIAL_HISTORY") puts features with 9 of 256 usable sessions in the same class as features missing a few early weeks. Use §2 of this review instead.
- Fix: label headings from the evidence policy names; split PARTIAL into "short window" and "early ramp-up". Not changed here (read-only review).

**Not done, as instructed:** no backfill rerun, no canonical mutation, no Stage 3, cron or model change.
