# Stage 4 E2: multi-session holding, design DRAFT

**Status:** DRAFT for approval. Nothing is implemented or run, and no label is built.
- **Research only:** no orders, no profitability claim.
- **Predecessor:** E1 (`docs/STAGE4_E1_RESULTS_P1.md`, `docs/STAGE4_E1_RESULTS_P2.md`). Neither predictor was accepted.

## Why E2

- **E1 found ranking information but no edge after costs.** Rank IC was 0.044 for reversal and 0.069 for ridge24 (t 4–7). The gross excess over matched controls (+0.05–0.08% per session) was not significant, and it was below about 3–4 bps per side of cost.
- **The open-to-close design pays a full round trip every session.** The ridge picks, however, persist: 14.5% daily name turnover against 78% for reversal. Holding for H sessions spreads one round trip over H days.
- **Real opening spreads are wide** (shadow log, 2026-10-12, top-500 universe):
  - first two-sided quote: median 27.7 bps;
  - median over 09:15–09:20: 9.9 bps (top 200: 7.7; ranks 201–500: 12.4).

  Crossing at the open costs about 5 bps per side in spread alone. This is one day's measurement; the shadow log extends it daily.
- **Caveat:** holding overnight is a delivery (CNC) trade. Statutory delivery costs (STT on both sides, stamp duty) are **much higher than intraday**. They must come from the confirmed fee schedule, so E2 also needs the approved cost model.

## Question

Does a long-only portfolio of point-in-time top-quintile picks, **held for H sessions**, earn more than liquidity- and volatility-matched controls **after turnover-aware costs**?

## Proposed design (each item to approve)

| Item | Proposal | Rationale |
|---|---|---|
| Horizon | **H = 5 primary**; H = 3 as a reported sensitivity only | One primary horizon keeps statistical power (2 predictors means Bonferroni 97.5%, as in E1) |
| Label | A new version `label-hold5-v1-asif`. The H-session return runs from the official open of T to the official close of T+4, gross. It is built like label-v2: `pit.bars_adjusted` at a recorded knowledge cutoff, with split and bonus adjustment inside the window. It is flagged `DIVIDEND_IN_WINDOW` (price-only return), `CA_IN_WINDOW` and `SESSION_MISSING`. | It needs a database write (additive label rows plus a label run), so it needs approval |
| Dataset | `stage4-ds-v3-asif`, PRE_SESSION (unchanged) | Only the as-if-live data has enough history |
| Universe, selection | As E1: the top 500 by `turnover_20` among feature-eligible names, top quintile, long-only, point-in-time only | Comparable to E1 |
| Portfolio | **Staggered tranches** (Jegadeesh–Titman). Each session T forms one tranche held for 5 sessions, so the book holds the 5 latest tranches at 1/5 weight each. The daily book return is the evaluation series. | Uses every session without overlapping observations at the book level. Turnover is the actual traded weight, not assumed |
| Predictors | P1 reversal (−`ret_1d`); P2 ridge24 retrained on the **H-session target rank** with E1's procedure (TRAIN fit, penalty chosen on VALID by mean rank IC) | Same comparison as E1, on the new horizon |
| Controls | C0 universe tranche book; C1 permutation; **C2 matched-control tranche book** (formation-day turnover × ATR decile cells); placebo | As E1 |
| Splits | A new scheme `wf-exp-120-20-20-e5`: the same blocks with a **5-session embargo**, because a 5-session label overlaps the next 4 sessions' features. It needs approval (additive split rows). | Purges the overlap between labels and later blocks |
| Primary metric | The mean daily **net** excess of the P-book over the C2-book under the approved cost model, with costs charged on the actual traded weights each session. A moving-block bootstrap (block 10, at least 2 × H) gives a 97.5% CI. | Net, because costs are the whole question. The gross figure is reported too. |
| Costs | Statutory delivery costs per side (approved schedule) plus measured half-spread at the open (shadow log median), and slippage swept at 0/5/10/20 bps per side | No invented rates |

## Acceptance criteria (proposed; per predictor)

| # | Criterion |
|---|---|
| A1 | The lower bound of the 97.5% CI of the **net** daily excess of the P-book over the C2-book is above 0 (PASS / FAIL if the upper bound is below 0 / otherwise UNPROVEN) |
| A2 | The net excess is still ≥ 0 at 1.5× the approved cost |
| A3 | Positive in at least 4 of 5 folds |
| A4 | The placebo-book CI includes 0 |
| A5 (P2) | P2's primary metric is above P1's, otherwise P2 is dropped |
| A6 | The maximum drawdown of the cumulative net excess is reported against the gross; there is no threshold, it is reported for the decision |

## Data, sample size, leakage

- **Sample:**
  - test sessions: 100 (2026-04-27 → 09-17), which is about 20 independent 5-day periods;
  - daily book returns: autocorrelated through the tranche overlap, which the block bootstrap handles;
  - minimum detectable effect: of the order of 0.1% per day. Smaller true effects will read UNPROVEN.
- **Leakage:**
  - the label spans T..T+4, which needs the 5-session embargo and a purged TRAIN;
  - selection reads only features at as_of;
  - corporate-action and dividend flags inside the window are reported and never used to select;
  - the label's knowledge cutoff is recorded.
- **Biases:**
  - survivorship (current master only) is worse over multiple days;
  - as-if-live knowability is assumed;
  - entry and exit are modelled at the official open and close;
  - overnight gap risk is real, and there is no stop in this design.
- **One look:** the validate phase reports no metric. The test look happens once per configuration hash and is recorded in the ledger.

## What E2 needs before it can run (approval list)

1. This design, including H = 5 and the acceptance criteria.
2. The cost model: the confirmed Upstox/NSE **delivery** and intraday fee schedule.
3. Building `label-hold5-v1-asif` and the `-e5` splits (additive production rows; backup first).
4. Writing the E2 script and its tests (by extension of E1).
5. Retraining P2 on the 5-session target (in memory, no stored model).
