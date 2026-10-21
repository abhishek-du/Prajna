# Stage 4 E5: ML prediction models, pre-registration (APPROVED IN PRINCIPLE 2026-10-21; FROZEN at `models freeze`)

**User decisions (2026-10-21):**
- libraries: scikit-learn, LightGBM and PyTorch (CPU);
- entry at the 09:15 open from the PRE_SESSION snapshot;
- a forward test of 40 sessions;
- a daily paper-only prediction job, migration 0024.

**PAPER ONLY. No order is ever placed, modified or cancelled.**

## 1. Question

Can an ensemble of ML models, using only information knowable at the PRE_SESSION snapshot (08:59:59 IST), pick a 10-name long-only intraday (MIS) book that beats matched controls after costs, open to close, on sessions it has never seen?

## 2. Why the test is forward

The historical windows were already looked at for open-to-close questions:
- E1 and E2 (2025-09 .. 2026-10);
- E4 (2021-01 .. 2026-09).

A new historical TEST would not be clean. So:
- **Development (exploratory):** walk-forward on the AS_IF_LIVE v3 dataset, `ops/measure/e5_develop.py`. It may change the recipe. Its numbers are labelled EXPLORATORY and are never a confirmatory result.
- **Confirmatory:** the 40 trading sessions after the freeze. Predictions are written before the 09:15 open, enforced by a database CHECK (`predicted_at < deadline_at`). There is one look at the end.

## 3. Recipe (`app/models/recipe.py`, `e5-recipe-v2`; frozen with the model's sha256)

**Universe (past-only):**
- NSE_EQ rows with all 24 core features (E1 CORE24);
- price (sma_20) ≥ ₹50;
- the top 500 by turnover_20.

**Inputs:** unit ranks per session (scale-free).

**Members (fixed hyperparameters, no tuning on a test block):**

| Member | Model | Target |
|---|---|---|
| ridge | ridge regression, α = 100 | ret_oc, winsorised 1 % / 99 % |
| lgbm_reg | LightGBM regression | ret_oc, winsorised |
| lgbm_clf | LightGBM classifier | up = ret_oc > the round-trip cost |
| rf_clf | random forest | up |
| lstm_clf | LSTM (32 hidden) over the last 10 sessions' ranks | up |
| lgbm_q10, lgbm_q90 | LightGBM quantile | ret_oc |
| lgbm_range | LightGBM regression | high/open − low/open |

**Outputs per stock** (the diagram's "Model Outputs"):

| Output | Definition |
|---|---|
| prob_up | mean of the three classifiers |
| exp_return | mean of the two regressors |
| range_lo / range_hi | q10 / q90 |
| volatility | predicted intraday range |
| confidence | 1 − 2 × the standard deviation of the five members' unit ranks |
| score | stacking-weighted mean of the members' unit ranks. Weights are max(IC, 0) on an inner validation of the last 20 training sessions; the members are then refitted on the whole window |

**Hybrid selection** (ML plus quant rules):
- exp_return > the round-trip cost (18.3 bps: MIS charges at ₹1 L per name plus a 5 bps half-spread on each side);
- prob_up > 0.5;
- not a known results-meeting day (results calendar);
- then the top K = 10 by score.

No candidate means no trade (cash).

**Training:**
- a rolling window of the latest 120 labelled sessions;
- seeds fixed;
- LightGBM deterministic; torch single-threaded and deterministic.

The frozen model is NOT retrained during the 40 sessions: the test is of one model. Periodic retraining is the walk-forward's rolling refit and, after the test, a new pre-registered model.

## 4. Primary metric and inference

- **Primary metric:** s_d = the picks' gross open→close − their MIS cost − the gross of matched controls (same turnover tercile × volatility tercile × ret_5d quintile cell, untraded; E4 machinery). A cash day is s_d = 0.
- **Outcomes:** canonical daily bars of the session. A missing or locked bar (high = low) is not evaluable.
- **Inference:** the sign-flip randomization CI at level 0.975 (E4 correction C2).
- **Minimum detectable effect** (development estimate): about 40 bps per session over 40 sessions. **An edge smaller than that will very likely read as NOT_ACCEPTED.** This is stated in advance.

## 5. Acceptance (all four)

| Gate | Rule |
|---|---|
| A1 | the CI of mean s_d lies above 0 |
| A2 | mean s_d at 1.5 × costs ≥ 0 |
| A3 | mean s_d > 0 in both halves (sessions 1–20 and 21–40) |
| A4 | placebo (random picks of the same count − their matched controls): the CI contains 0 |

- ACCEPTED means Stage 5 may use the model in paper trading. NOT_ACCEPTED means the model is not used, and the result is reported as it is.
- Secondary metrics (reported, never decisive): AUC, accuracy, Brier, IC (and its t), hit rate, precision and recall of the picks, range coverage, volatility rank correlation, Sharpe and drawdown of the net book.
- No interim look: `prajna models status` shows counts only. `prajna models report --look` is refused before 40 closed sessions and refused a second time (ledger).

## 6. Operations

- Migration 0024 adds `model_version` and `model_prediction`, both append-only.
- `prajna models freeze --commit` stores `var/models/<sha>/bundle.pkl` and its sha256, and refuses a dirty tree.
- `ops/runbooks/model_predict.sh` is proposed for cron at 09:06 Monday–Friday (the user installs it). It waits until 09:13 for today's Stage 3 PRE_SESSION run, then runs `models predict --commit`; the code refuses at or after the open.
- **Known blocker (2026-10-21):** the Stage 3 PRE_SESSION run now finishes at 09:20–09:28. Its lock check evaluates the full Stage 1 gate on the 150 GB database. The forward test starts only after that is fixed.

## 7. Development results (EXPLORATORY; e5-recipe-v1, 2026-10-21)

- **Sample:** 4 folds, 74 out-of-sample sessions, 2026-06-24 .. 2026-10-09.
- **Ranking and classification:** AUC 0.536, IC 0.056 (t 5.4).
- **Range and volatility:** range coverage 78 % (target 80 %), volatility rank correlation 0.66.
- **Book:** mean s_d +8 bps, CI [−16, +34] bps.
- **Trading:** 49 of 74 sessions were cash (few names clear the cost).
- **Member ICs:** ridge 0.061, lgbm_reg 0.043, lgbm_clf 0.028, rf_clf 0.018, lstm_clf −0.000. v2 adds the stacking weights for this reason.
