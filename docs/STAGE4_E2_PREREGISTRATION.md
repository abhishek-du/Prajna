# Stage 4 E2: multi-session holding, pre-registration (DRAFT, not approved to run)

**Status:** DRAFT. It supersedes `docs/STAGE4_E2_DESIGN_DRAFT.md` and resolves the 9 audit items below.
- **Not run:** no label is built, no split is written, and the test look has not happened.
- **Research only:** no order, no profitability claim. A failed E2 never unlocks trading.

**Code:**
- `backend/app/training/e2.py` holds the pure computation;
- `backend/tests/training/test_e2.py` holds its 21 synthetic tests;
- `backend/ops/measure/upstox_charges.py` fetches the cost evidence (read-only).

## What this experiment can and cannot establish (read first)

- **Sample:** 100 TEST sessions (2026-04-27 → 09-17), as in E1.
  - With H = 5 that is about **20 independent 5-session periods**.
  - The effective sample of the daily book excess lies between 20 and 100, depending on how strongly overlapping tranches correlate.
- **Power** (from E1's per-session matched excess):
  - reversal: per-session sd 0.40%; ridge24: 0.30%;
  - the minimum detectable mean daily excess at about 80% power is **0.08–0.19% per day** for ridge24 and **0.11–0.25% per day** for reversal (the range is independent periods vs fully overlapping).
- **Costs to beat** (illustrative; the actual model is in the cost section):
  - delivery charges at ₹1 L per order are about **27 bps per round trip**, before the half-spread;
  - a fully rotated 5-tranche book trades about 20% of its value per side per day, so it pays roughly **5–8 bps per day**.
- **Implication:**
  - E1's gross matched excess was 0.05–0.08% per day (open to close).
  - Unless the 5-session effect is several times larger, the expected E2 verdict is **UNPROVEN** (CI includes 0), and possibly FAIL net of costs.
  - E2 can establish a large net edge, or rule one out. It cannot establish a small one.
- **Knowability:**
  - only 11 sessions are STRICT point in time; the rest are as-if-live with **assumed** knowability;
  - the universe is the current master (survivorship bias, worse over multiple days).
  - Every result is provisional.

## 1. Target and corporate actions

- **Entry and exit:** a tranche is formed from session T's PRE_SESSION features, **bought at the official open of T and sold at the official open of T+5**.
  - **Change from the draft:** the draft exited at the close of T+4. Exiting at the open lets the outgoing and incoming tranches net out at one price, and no capital sits overnight in cash.
- **Label `label-hold5-v1-asif`:** `open[T+5] / open[T] − 1`, built from `pit.bars_adjusted` at a recorded knowledge cutoff.
  - Splits and bonuses are back-adjusted, so a split inside the window is not a crash (`test_split_inside_the_window_is_adjusted_not_a_loss`).
  - **Primary: price only.**
  - **Reported sensitivity: total return** = plus the cash of every dividend with an ex-date in (T, T+5], i.e. the holder of record (`hold_label(dividends=…)`).
  - Flags: `CA_IN_WINDOW`, `DIVIDEND_IN_WINDOW`, `SESSION_MISSING` (no open at T or T+5) and `NO_EXIT_SESSION`. Flags are reported and never used to select.
- **Evaluation series:** the daily book is valued **open to open**.
  - A held name without an open the next session is marked flat and counted (`missing_marks`).
  - Suspensions bias the result. Their count is reported.

## 2. Universe and eligibility (unchanged from E1)

- **Universe:** point in time at T PRE_SESSION. Take the top 500 by `turnover_20` among names whose 24 core features are VALID, and pick the top quintile (100 names), long only.
- **No rescue:** a pick without an open at T is skipped, and the tranche is equal weight over the rest.

## 3. Splits, purging and embargo: scheme `wf-exp-120-20-20-e5`

- **Blocks:** TRAIN at least 120 sessions, then a **5-session embargo**, VALID 20, a 5-session embargo, TEST 20; the blocks roll by 20.
- **Purging:** the last h sessions of the data are never TEST, because a TEST label needs the open of T+5. With embargo ≥ H, no TRAIN or VALID label window [T, T+5] reaches the next block (`make_folds`; this is tested, and a shorter embargo is refused).
- **Warm-up:** each TEST block's book is warmed up with the 4 tranches formed in the 4 sessions before TEST. They are traded but not evaluated. Those sessions are embargo or VALID sessions, and only their features are used.
- **Fold boundaries move:** they will shift against E1. The exact TEST dates are printed by the validate phase before the test look.

## 4. Portfolio construction and accounting (`tranche_book`)

- **Tranches:** there are H = 5 tranches of 1/5 each, equal weight within each tranche. Weights drift with prices.
- **Rotation:** at each open, the expiring tranche's value buys the new tranche. Trades are **netted per name**, and turnover is what was actually traded.
- **Ramp:** the book starts in cash and adds 1/5 per formation.
- **Exposure:** fully invested after the ramp. If no pick is buyable, that 1/5 stays in cash.
- **Tested:** ramp, staggering, netting, drift and compounding, and flat marking for suspensions.

## 5. Controls and placebo

| Control | Construction |
|---|---|
| **C2 (primary)** | For every formation-day pick, a seeded random, not-picked universe name from the same (turnover decile × ATR decile) cell, without replacement. Unmatched picks are counted. The C2 tranche book uses identical accounting and **identical costs**. |
| C0 | The equal-weight universe tranche book (context only) |
| C1 | Score permutation within each formation day → a book-level p-value (200 draws) |
| Placebo | The same number of random non-picked names per formation day, against their own C2 controls. Its CI must include 0 (A4). |

## 6. Transaction costs: rates PENDING APPROVAL

### Source and date

- **Source:** Upstox `GET /v2/charges/brokerage`, fetched **2026-10-13T09:36:18Z**.
  - 16 orders: delivery (D) and intraday (I) × BUY/SELL × ₹10 k–₹5 L, RELIANCE at ₹1,158.90.
  - Raw responses are in `backend/var/stage4/costs/charges_20261013T093619Z.json`.
- **Derived rates:** the rates below are derived from those responses.
  - `order_cost_inr` reproduces all 16 totals to within ₹0.03 (`test_rates_reproduce_the_broker_charges_api`).
  - Official NSE/SEBI/state circulars for the statutory parts are **not yet cross-checked**. That is part of the approval.

| Charge | Delivery (CNC) | Intraday (MIS) |
|---|---|---|
| Brokerage per order | ₹20 flat | min(₹20, 0.06% of value) |
| STT | 0.1% buy and sell | 0.025% sell |
| Stamp duty | 0.015% buy | 0.003% buy |
| Exchange transaction | 0.00307% | 0.00307% |
| SEBI fee | 0.0001% | 0.0001% |
| GST | 18% on brokerage + exchange + SEBI | same |
| DP charge | **Not in the API total.** The response names plan `DP4A`, `min_expense` ₹20 per scrip per sell day. **To confirm** (amount, GST). | n/a |

### Round-trip examples (delivery, excluding DP)

| Order size | Buy | Sell | Round trip |
|---|---|---|---|
| ₹10 k | 34.5 bps | 33.0 bps | about 68 bps |
| ₹1 L | 14.2 bps | 12.7 bps | about 27 bps |
| ₹5 L | 12.3 bps | 10.8 bps | about 23 bps |

**The flat ₹20 makes cost depend on position size:** a ₹10 L book spread over 100 names × 5 tranches (₹2 k orders) pays more than 100 bps per side.

### Spread and slippage (kept separate, never double counted)

- **Half-spread at the open, measured:** from the pre-open capture between 09:15 and 09:20, top 500, median spread 9.9 bps, so the half-spread is about **5 bps**.
  - This is one day so far (2026-10-12); the shadow log extends it.
  - The first-quote median is 27.7 bps, which is the pessimistic bound.
- **Slippage:** impact *beyond* the half-spread, swept at 0 / 5 / 10 / 20 bps per side. It is a sensitivity, not part of A1.

### Decisions for you

| # | Decision | Proposed |
|---|---|---|
| C1 | Book capital | ₹1 Cr. 100 names × 5 tranches gives about ₹2 L per position. |
| C2 | DP charge per scrip per sell day | ₹20 + 18% GST, to confirm against the account plan |
| C3 | Primary half-spread | 5 bps: the measured median over 09:15–09:20 |
| C4 | Primary slippage | 0 bps; the 5/10/20 bps sweep is reported |
| C5 | Statutory cross-check | Against the official NSE, SEBI and Maharashtra stamp duty sources |

## 7. Inference

- **Primary series:** the daily net excess of the P-book over the C2-book.
- **Bootstrap:** a moving-block bootstrap with **block 10 (= 2H)** and 10,000 draws, giving a two-sided 97.5% CI (Bonferroni over 2 predictors).
  - A block shorter than 2H is refused (tested).
  - A block of 20 is reported as a sensitivity.
- **Also reported:** a Newey-West t-statistic with lag 2H − 1.

## 8. Acceptance (per predictor, fixed before the look)

| # | Criterion |
|---|---|
| A1 | The **net** C2 excess CI lower bound is above 0: PASS. The upper bound is below 0: FAIL. Otherwise UNPROVEN. |
| A2 | The net mean is still ≥ 0 at 1.5× the approved costs |
| A3 | Net positive in at least 4 of 5 folds |
| A4 | The placebo CI includes 0 |
| A5 (P2) | P2's net mean is above P1's, otherwise P2 is dropped |
| A6 | Maximum drawdown, net vs gross. Reported, no threshold. |

## 9. Report contents and reproducibility

- **Per predictor:**
  - gross and net mean with CIs;
  - fold means;
  - turnover, positions, and costs split into statutory, brokerage, spread and slippage;
  - the C0/C1/C2 and placebo results;
  - drawdown;
  - unmatched, `missing_marks` and corporate-action-flag counts;
  - the price-only vs total-return sensitivity.
- **Provenance:** the configuration sha256 and code git sha (clean tree).
- **One look:** validate (no metric) and test (once per configuration, ledgered), as in E1.
- **Predictors:**
  - P1: reversal (−`ret_1d`);
  - P2: ridge24 retrained in memory on the rank of the 5-session label (TRAIN fit, penalty chosen on VALID by mean rank IC).
  - No XGBoost, LSTM or ensemble. They are not justified while the linear baselines are below cost.

## Approvals required before anything runs

1. This protocol: the open-to-open exit, price-only primary, H = 5, and the acceptance criteria.
2. Cost decisions C1–C5.
3. Building `label-hold5-v1-asif` and the `wf-exp-120-20-20-e5` splits in production. These are additive rows, with a backup first.
4. The E2 runner script: validate, then the single test look.
