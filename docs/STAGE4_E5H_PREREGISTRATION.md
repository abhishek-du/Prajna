# Stage 4 E5-H: the frozen E5 model on 2020, a historical holdout (pre-registration, APPROVED 2026-10-23; FROZEN before any 2020 outcome is computed)

**User decisions (2026-10-23):**
- "haan E5-H approve, poora 2020 window rakho".
- Backfill Oct–Dec 2019 daily bars from Upstox for the warm-up ("2019 Q4 backfill karo").

**PAPER RESEARCH ONLY. No order is ever placed, modified or cancelled.**

## 1. Question

Does the **frozen** E5 model (`4db89a70…`, recipe `e5-recipe-v2`, trained on 2026-04-17..10-08) pick a 10-name long-only intraday (MIS) book that beats matched controls after costs, open to close, on the 2020 sessions?
- The model has never seen 2020.
- No research test has looked at 2020 open-to-close outcomes.

## 2. Why 2020 is clean, and what is disclosed

**Every other period is taken:**

| Window | Used by |
|---|---|
| 2021-01..2026-09 | the E4 TEST window (open → close) |
| 2025-09..2026-10 | E1 and E2 |
| 2026-04..10 | E5 development and training |
| from 2026-10-22 | the E5 forward test (open) |

**2020 so far:**
- E3 used 2020 only as feature warm-up.
- The E4 design used it only to describe data availability.

**Disclosed:** on 2026-10-23, before this file, the results event study (`ops/measure/e6_results_event_study.py`) computed 2020 Nifty-relative close-to-close returns around results announcements. That is a different question: 20-day post-results drift, not the open-to-close of model picks. **No E5 prediction, pick or open → close outcome for 2020 has been computed.**

## 3. Model and recipe (unchanged; inference only)

- Bundle `var/models/4db89a70…/bundle.pkl`, sha verified at load. No refit, no tuning, no threshold change.
- **Universe** (past-only, the same as E5): NSE_EQ rows with all 24 CORE24 features; sma_20 ≥ ₹50; top 500 by turnover_20.
- **Selection** (the same as E5):
  - exp_return > the round-trip cost (18.3 bps);
  - prob_up > 0.5;
  - top K = 10 by score;
  - none means cash.
- **Results-day exclusion:** E5 skips known results-meeting days. For 2020 this uses the F4 NSE results dates (HISTORICAL_FILING): a name whose results dissemination falls on the session or the previous evening is excluded. This is the closest available equivalent of the live INTIMATION calendar, and it is stated here before the run.
- **LSTM history:** the previous 9 sessions of the same dataset (from the warm-up).

## 4. Data (AS_IF, research only; flagged ASSUMED)

| Item | Definition |
|---|---|
| Bars | canonical 1d VENDOR_ADJUSTED bars. 2020 bars were fetched on 2026-09-23; 2019-09-01..12-31 bars (warm-up) are fetched on 2026-10-23 through the standard Upstox ingest (`ingest candles --timeframe 1d`) |
| Knowable | a bar at its session close (AS_IF). The vendor's adjustment is accepted as is (`allow_low_confidence`; these bars are older than the corporate-action horizon). Every row carries the flag `PRICE_LEVEL_VENDOR_ADJUSTED` |
| Features | the production engine (`engine.compute_snapshot`), PRE_SESSION snapshots for every 2020 session plus the 9 sessions before 2020-01-01. A new dataset version `stage4-ds-h2020` (frozen after the build) |
| Labels | `label-h2020`: ret_oc = close / open − 1, high_exc, low_exc from the same bars. Malformed bars (high < low, open or close outside [low, high], non-positive) → NOT VALID |
| Evaluation mask | E5's masks cannot apply: there are no 2020 corporate-action data, and every row has the vendor-adjusted flag. Instead a name-session is masked when \|ret_1d\| or the opening gap exceeds 25 % (an unexplained extreme), or the session's high equals its low (a locked circuit; no fill) |
| Basis break | the 2019 warm-up bars are adjusted as of 2026-10-23, the 2020+ bars as of 2026-09-23. **Any instrument with a price-factor corporate action ex-date in (2026-09-23, 2026-10-23] is excluded from the whole test.** A name whose first-2020 open / last-2019 close differs by more than 25 % is excluded for the sessions whose features use both years (to 2020-03-31) |
| Survivorship | only names listed today exist in the data (about 1,700 names had 2020 bars). The matched controls come from the same universe, so the relative metric is less affected. Stated, not corrected |

## 5. Primary metric, inference and gates (the same as E5 §4–§5)

- **s_d** = the picks' gross open → close − their MIS cost (E4 SessionCost, ₹1 L per name, today's charges) − the gross of matched controls (turnover tercile × volatility tercile × ret_5d quintile, untraded). A cash day is s_d = 0. A session with fewer than 20 evaluable names is not evaluable.
- **Inference:** the sign-flip CI of mean s_d at level 0.975.
- **Sessions:** every 2020 trading session with a usable PRE_SESSION snapshot, about 250. The COVID crash (Feb–Mar 2020) is inside, as chosen.
- **Minimum detectable effect** (from the E5 development sd of s_d, about 96 bps): about 17 bps over 250 sessions.

| Gate | Rule |
|---|---|
| A1 | the CI of mean s_d lies above 0 |
| A2 | mean s_d at 1.5 × costs ≥ 0 |
| A3 | mean s_d > 0 in both halves (sessions 1–125 and 126–end) |
| A4 | placebo (random picks of the same count − their matched controls): the CI contains 0 |

**Secondary** (reported, never decisive): AUC, accuracy, Brier, IC (t), hit rate, precision, recall, range coverage, volatility rank correlation, Sharpe and maximum drawdown of the net book, results by quarter, and Jan–Mar vs Apr–Dec.

## 6. What the result means

| Result | Meaning |
|---|---|
| ACCEPTED-HISTORICAL | the E5 edge exists out of time on 2020. Stage 4 is complete: model, outputs, training and an out-of-sample evaluation. The forward test continues unchanged as the confirmation |
| NOT_ACCEPTED | reported as it is. Stage 4 is complete with a negative answer: the model is not used by Stage 5 before its forward look; E5.1 / E6 continue |

- **The forward test is not touched either way.** No interim look, the same 40 sessions, the same look.
- **One look only:** `models report-h2020 --look` writes a ledger and refuses a second time.
- Development numbers, sensitivity runs and plots of 2020 outcomes before the look are not allowed.

## 7. Steps (in this order)

1. This file is committed and frozen: the sha of this file and of the code at the build go into the ledger.
2. Upstox backfill of 2019-09-01..12-31 daily bars (all current NSE_EQ + NSE_INDEX). Dry run first, then `--commit`.
3. Build `stage4-ds-h2020` (PRE_SESSION, 2019-12-17..2020-12-31) and `label-h2020`. Verify: counts, no duplicate, PIT (feature knowable < 09:15 of the session), the basis-break exclusions.
4. Predict every session with the frozen bundle (read-only, written to a research table or file, not `model_prediction`).
5. The single look; report `docs/STAGE4_E5H_RESULTS.md`; the Stage 4 completion report.
