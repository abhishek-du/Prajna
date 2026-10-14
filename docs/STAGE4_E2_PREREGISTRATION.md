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
  - delivery charges including DP are about **29 bps per round trip** at ₹1 L per order and about 51 bps at ₹25 k, before the half-spread;
  - a 5-tranche book of 500 positions trades 10–20% of its value per side per day: **6.8–13.5 bps per day at ₹1 Cr** and 3.9–7.9 at ₹5 Cr (section 6).
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

### Sources, in order of precedence

1. **The account's own charges**, from Upstox `GET /v2/charges/brokerage`, fetched **2026-10-13T09:36:18Z**.
   - 16 orders: delivery (D) and intraday (I) × BUY/SELL × ₹10 k–₹5 L, RELIANCE at ₹1,158.90.
   - Raw responses are in `backend/var/stage4/costs/charges_20261013T093619Z.json`.
   - `order_cost_inr` reproduces all 16 totals to within ₹0.03 (`test_rates_reproduce_the_broker_charges_api`).
2. **The NSE transaction charge:** NSE circular of **2026-02-27, effective 2026-03-01**.
   - Cash market: ₹306.99 charges + ₹0.01 IPFT = **₹307 per crore per side (0.00307%)**.
   - Before that: ₹297 + ₹10 IPFT, also ₹307 in total.
   - The circular PDF (`nsearchives.nseindia.com/content/circulars/FA73061.pdf`, number to be confirmed) timed out when fetched. The figures come from TeamLease RegTech's and Upstox News's summaries of it, and they agree with the API.
3. **Upstox pricing page** (`upstox.com/brokerage-charges`, read 2026-10-13; it shows no last-updated date):
   - delivery brokerage ₹20 per executed order;
   - STT 0.1% buy and sell (from 2024-10-01);
   - stamp duty 0.015% on the buy side;
   - SEBI ₹10 per crore;
   - GST 18% on brokerage + transaction + demat + IPFT;
   - **DP ₹20 per scrip per day on sells, plus GST**.

| Charge | Delivery (CNC) | Source | Intraday (MIS), reference only |
|---|---|---|---|
| Brokerage | ₹20 per order, flat | API (all sizes) and the pricing page | min(₹20, 0.06%): API. **The page says 0.1%;** the API is account-specific and is used. |
| STT | 0.1% buy and sell | API; the page (from 2024-10-01) | 0.025% sell |
| Stamp duty | 0.015% buy | API; the page | 0.003% buy |
| Exchange transaction (incl. IPFT) | 0.00307% each side | API; NSE circular 2026-02-27 | same |
| SEBI fee | 0.0001% (₹10 per crore) | API; the page | same |
| GST | 18% on brokerage + exchange + SEBI (+ DP) | API; the page | same |
| **DP charge** | **₹20 + 18% GST = ₹23.60 per scrip per sell day** | The page. The API names plan `DP4A`, `min_expense` ₹20, and **excludes it from its total**, so it is added separately. | none |

**C5, statutory cross-check (2026-10-13).** Every rate agrees with the broker's live computation. Primary government texts could not be retrieved from this host: incometaxindia.gov.in returned HTTP 403, and nseindia.com timed out.

| Charge | Rate | Legal basis | Evidence retrieved | Status |
|---|---|---|---|---|
| STT, delivery | 0.1% buy and sell | Finance (No. 2) Act 2004, Chapter VII (s. 98); rates from 2024-10-01 | Upstox pricing page; secondary summaries; the API | **Confirmed by the broker's computation; primary text not retrieved** |
| STT, intraday | 0.025% sell | same | Upstox pricing page; the API (24.92 on ₹99,665) | same |
| Stamp duty | 0.015% delivery buy, 0.003% intraday buy | Indian Stamp Act 1899 as amended by the Finance Act 2019; Collection Rules notified 2019-12-10; **effective 2020-07-01** | Professional summaries (iPleaders, Khaitan & Co, Mondaq); the API (14.95 on ₹99,665) | **Confirmed by the broker's computation; Gazette text not retrieved** |
| SEBI turnover fee | 0.0001% (₹10 per crore) | SEBI (Stock Brokers) Regulations fee schedule | The API (0.10 on ₹99,665); secondary sources. The sebi.gov.in page found is a 2020 *proposal*, not the current rate. | Confirmed by the broker's computation |
| GST | 18% | GST on financial services, SAC 997152 | The API (4.17 on ₹20 + ₹3.06 + ₹0.10) | Confirmed by the broker's computation |
| NSE transaction charge | 0.00307% (₹306.99 + ₹0.01 IPFT per crore) | NSE circular 2026-02-27, effective 2026-03-01 | TeamLease RegTech and Upstox News summaries; the API | Confirmed |

**Reading:** every statutory figure the cost model uses is reproduced exactly by Upstox's own charges computation for this account on 2026-10-13. The remaining gap is document provenance (the Gazette and Income Tax texts), not the rate.


### Order-size sensitivity (delivery, incl. DP; `e2.order_cost_inr`)

| Order | Buy | Sell | Round trip |
|---|---|---|---|
| ₹2,000 | 129.9 bps | 246.4 bps | 376 bps |
| ₹10,000 | 35.5 | 57.6 | 93 |
| ₹25,000 | 21.3 | 29.3 | 51 |
| ₹50,000 | 16.6 | 19.8 | 36 |
| ₹1,00,000 | 14.2 | 15.1 | 29 |
| ₹2,00,000 | 13.1 | 12.7 | 26 |
| ₹5,00,000 | 12.4 | 11.3 | 24 |

### Book cost per day by capital

The book holds 100 names × 5 tranches (500 positions) with a 5 bps half-spread. Turnover is one-sided, at 10% (with netting) or 20% (no netting).

| Capital | Order size | 10% turnover | 20% turnover |
|---|---|---|---|
| ₹10 L | ₹2,000 | 38.6 bps/day | 77.3 |
| ₹50 L | ₹10,000 | 10.3 | 20.6 |
| ₹1 Cr | ₹20,000 | 6.8 | 13.5 |
| ₹5 Cr | ₹1 L | 3.9 | 7.9 |
| ₹10 Cr | ₹2 L | 3.6 | 7.2 |

**Below ₹5 Cr the flat brokerage and DP dominate.** At ₹1 Cr the costs alone are 6.8–13.5 bps per day, against E1's best gross matched excess of 5–8 bps per day.

### Spread and slippage (kept separate, never double counted)

- **Half-spread at the open, measured:** from the pre-open capture between 09:15 and 09:20, top 500, median spread 9.9 bps, so the half-spread is about **5 bps**.
  - This is one day so far (2026-10-12); the shadow log extends it.
  - The first-quote median is 27.7 bps, which is the pessimistic bound and is reported.
- **Slippage:** impact *beyond* the half-spread, swept at 0 / 5 / 10 / 20 bps per side. It is a sensitivity, not part of A1.

### Decisions for you

| # | Decision | Proposed |
|---|---|---|
| C1 | Book capital, which sets the order size | **Your decision** (account size is not known to me). Placeholder: primary ₹1 Cr (₹20 k orders). Report ₹10 L, ₹50 L, ₹5 Cr and ₹10 Cr. *Correction: an earlier draft wrote "₹1 Cr ≈ ₹2 L per position"; that is ₹10 Cr.* |
| C2 | DP charge | ₹20 + 18% GST per scrip per sell day (the pricing page; excluded from the API total) |
| C3 | Primary half-spread | 5 bps (measured median 09:15–09:20); 13.9 bps (first quote) reported |
| C4 | Primary slippage | 0 bps; 5/10/20 bps reported |
| C5 | Statutory cross-check | Fetch the official STT and stamp-duty texts before the look; NSE is done (2026-02-27 circular) |

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

## Amendment 1 (2026-10-14): approved cost decisions; corrections

Appended, not rewritten: everything above stays as written on 2026-10-13. The protocol itself is still **DRAFT**. Approvals 1, 3 and 4 above are still open, and three proposed changes are pending (`docs/STAGE4_E2_PROTOCOL_CHANGE_PROPOSAL.md`).

**Approved by the user 2026-10-14 (C1–C4); C5 status recorded:**

| # | Decision |
|---|---|
| C1 | Simulated research capital: **primary ₹10,00,000**; sensitivities ₹50,00,000, ₹1,00,00,000 and ₹5,00,00,000. Simulated assumptions only; not an authorization to trade. This replaces the ₹1 Cr placeholder of section 6. At ₹10 L a 100-name × 5-tranche book trades about ₹2,000 orders (376 bps per round trip; 38.6–77.3 bps per day, section 6). |
| C2 | DP ₹20 + 18% GST = ₹23.60 per scrip per sell day. The account's plan per the charges API is `DP4A`, `min_expense` ₹20, which the API excludes from its total. **Remaining uncertainty:** the API does not state whether ₹20 is per scrip per day or a minimum. The pricing page says per scrip per day, and that is used. |
| C3 | Measured opening half-spread per name where reliable data exists; otherwise a **5 bps provisional proxy**, with the coverage reported (`CostModel.half_spread_by_name`, `spread_coverage`). The pre-open capture starts 2026-09-24, so at most 4 of the 100 TEST sessions can have a measured spread: **the proxy will price at least 96% of TEST trades.** |
| C4 | Slippage 0 bps per side base; 5 / 10 / 20 bps sensitivity. Slippage is impact beyond the half-spread. The two are separate cost parts (`COST_PARTS`: brokerage, statutory, dp, spread, slippage; `cost_summary` reports gross, each part and net, each counted once). |
| C5 | Unchanged: every statutory rate agrees with the broker's computation. That is **not** verification against the primary legal texts (Finance Act / Income Tax and Gazette texts not retrieved). The gap remains open. |

**Corrections found by the 2026-10-14 audit:**
- **TEST dates:** "What this experiment can and cannot establish" says 2026-04-27 → 09-17 "as in E1". `make_folds(257)` gives **2026-05-08 → 2026-09-29**, as section 3 anticipates. **92 of the 100 E2 TEST sessions were E1 TEST sessions** (see PC-2).
- **Tests:** `test_e2.py` now collects 25 tests.
- **Code defect fixed** (`tranche_book`):
  - A held name's move between its last open and its reopening after a suspension was never booked. The drift used open(d) → open(d+1) and dropped both legs around a gap.
  - It now drifts from the last valid open, so the move is booked on reopening. `missing_marks` still counts the flat days.
  - Regression test: `test_a_move_across_a_suspension_is_booked_when_the_name_reopens`.
  - It fails on the old code. Nothing had been run with the old code.
