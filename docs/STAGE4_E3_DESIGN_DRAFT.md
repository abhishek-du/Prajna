# Stage 4 E3: monthly, low-turnover selection, design draft (NOT APPROVED, NOT BUILT, NOT RUN)

**Status:** DRAFT, 2026-10-14.
- **Purpose:** a design for review. No code, no labels, no splits and no look exist.
- **Why E3 exists:** E1 and E2 showed a small but real **gross** selection signal (C1 p ≤ 0.03, about 5 bps per day). The cost of harvesting it daily at ₹10 L is 15–19 bps per day (`docs/STAGE4_E2_RESULTS.md`).
  - Costs are flat fees per order (brokerage ₹20, DP ₹23.60) plus 0.1% STT on both sides, and they scale with **turnover**.
  - E3 therefore tests whether a **monthly** design, with few and large orders, can clear its much lower cost hurdle.
- **What E3 is not:**
  - not a re-test of reversal or ridge24 on the spent E1/E2 period;
  - not a more complex model.

## 0. Facts this design rests on (production, read-only, 2026-10-14)

| Fact | Value | Consequence |
|---|---|---|
| Daily bars (NSE_EQ) | 2020-01-01 → 2026-10-13, 1,685 sessions | About 80 monthly periods are possible; E1/E2 had 257 sessions |
| Price basis before 2025-09 | **VENDOR_ADJUSTED** for all 2,918 instruments | `pit.bars_adjusted` refuses them (LOW confidence: older than the corporate-action horizon). E3 must **explicitly assume** the vendor's split/bonus adjustment (A-1). |
| Corporate-action history | split/bonus from 2025-09-26 only (146) | No independent check of vendor adjustments before then; residual errors are caught by the mask (§5) |
| Instruments with bars | 1,693 (2020) → 2,071 (2022) → 2,702 (2024) → 3,573 (2026) | **Survivorship bias:** delisted names are absent from early years (A-2) |
| Fundamentals, news, pre-open history | about 3 weeks | **Not usable for E3.** E3 is price/volume only; fundamentals come in a later experiment. |
| Feature registry | features-v4 (active), unchanged | E3's signals are computed inside the experiment from the same bars; **no registry change** |

## 1. Hypotheses (2 predictors, Bonferroni, parameter-free: nothing is fitted)

| | Predictor | Definition at formation date F (closes ≤ F only) | Rationale |
|---|---|---|---|
| **P1** | 12-1 momentum | close(F − 21 sessions) / close(F − 252 sessions) − 1 | The best-documented cross-sectional anomaly at a monthly horizon; skipping the last month avoids the 1-month reversal that E1 measured |
| **P2** | 52-week-high proximity | close(F) / max(high over F − 251 … F) | A low-turnover, momentum-related signal with a different construction |

- Both are rule-based, so there are **no hyperparameters and no train/validate fitting**. The whole sample is a single test, with no tuning possible.
- A5-style comparison: P2 is kept only if its primary mean exceeds P1's.

## 2. Timing (one convention)

- **Formation F:** the last trading session of each calendar month. Signals use bars knowable after F's close (as-if-live: a daily bar is knowable at 16:00 IST of its session).
- **Entry:** the official open of the first session of the next month (F + 1). **Exit:** the official open of the first session of the month after.
- **Holding:** about 21 sessions, with **non-overlapping** monthly portfolios: no tranches, and one inference unit per month.
- **No look-ahead:** the label window starts at the F + 1 open, after F's close (tested, as in E1/E2).

## 3. Universe and selection

- **Universe at F:**
  - the top 500 NSE_EQ names by median 60-session turnover;
  - with ≥ 260 sessions of history;
  - with a close ≥ ₹20;
  - with **no** data-quality flag (§5) in the 252-session lookback (past information only).
- **Picks:** the top **K = 10** by score (ties by instrument key), equal weight.
  - At ₹10 L that is ₹1 L per order (29 bps per round trip incl. DP, plus spread).
  - **Sensitivities, not co-primary:** K = 20 and K = 30.
- **Rebalancing with netting:** names held over and re-picked are not traded. Turnover is what is actually traded.

## 4. Metric, controls and costs (E2's machinery, monthly)

- **Primary series:** monthly s_m = `P_gross,m − cost_m(P) − C2_gross,m` (PC-1a: costs on P only, and C2 is untraded).
- **Costs:**
  - approved C1–C4: ₹10 L primary; ₹50 L, ₹1 Cr and ₹5 Cr reported;
  - DP ₹23.60;
  - measured half-spread where reliable, else 5 bps;
  - slippage 0, with 5 / 10 / 20 bps.
  - Cost parts are counted once (`e2.order_cost_parts`).
- **Controls:**
  - **C2:** per pick, a random non-picked universe name of the same (turnover decile × 60-session volatility decile) cell, held identically;
  - **C0:** the equal-weight universe;
  - **C1:** 1,000 permutations of the score within each month;
  - **placebo:** random non-picked names against their own C2, on gross returns.
- **Reported, never gated:**
  - `P_gross − C2_gross`;
  - `P_net − C2_net`;
  - absolute `P_net`;
  - C0;
  - turnover, drawdown and concentration.

## 5. Data-quality mask (E2 Amendment 3, adapted; past information for eligibility)

- **Suspect session:** a daily |close-to-close| or |gap| move > 25% with no EXACT split/bonus factor (`EXTREME_UNEXPLAINED`), or an unsupported corporate action.
- **Eligibility (past only):** a name with a suspect session in its lookback is not eligible at F.
- **Evaluation (holding window):** a pick with a suspect session in (F, exit] is dropped from **every** arm after selection, as in E2. The unmasked result is a sensitivity.

## 6. Sample, inference and acceptance

**TEST:**
- every formation month from **2021-01** (12 months of warm-up from 2020-01) to **2026-08**, about **68 months**;
- one single look, ledgered as in E1/E2.

**Spent period:** E1/E2 tested different hypotheses, so the months 2026-04 → 2026-09 are not spent for E3. Because the researcher has seen them, they are also reported **excluded** (sensitivity).

**Inference:**
- studentized moving-block bootstrap of mean(s_m): block 3 months, 10,000 draws, 97.5% two-sided;
- Newey-West t, lag 2.
- **Pre-look requirement:** a new 1,000-world null calibration for this monthly design, with the same pre-set criteria as E2 (false-acceptance Wilson upper bound ≤ 2.5%; two-sided interval contains 2.5%, or a waiver on the conservative side only).

| # | Gate (per predictor, K = 10, ₹10 L) |
|---|---|
| A1 | CI of mean(s_m): lower bound > 0 is PASS; upper bound < 0 is FAIL; otherwise UNPROVEN |
| NW | The NW t agrees with A1 (≥ 2.2414 for PASS) |
| A2 | mean(s_m) ≥ 0 with every cost part × 1.5 |
| A3 | mean(s_m) > 0 in ≥ 4 of 6 calendar-year blocks (2021 … 2026) |
| A4 | The placebo CI includes 0 |
| A5 (P2) | P2's mean(s_m) > P1's |
| A6 | Maximum drawdown and worst 12-month s reported |

**ACCEPTED-EXPLORATORY** requires A1 PASS with NW agreement, plus A2–A4 (and A5). It is followed by a **forward** paper-only confirmation on months after the freeze date.

## 7. Power and cost arithmetic (to be recomputed from data before approval)

- **Cost hurdle at ₹10 L, K = 10:**
  - about 29 bps per round trip, plus about 10 bps of spread;
  - with 50–100% of the book traded per month, that is **about 0.2–0.4% per month**, i.e. **about 1–2 bps per day**, against 15–19 for E2 k20.
- **Precision:** assuming a matched monthly excess sd of about 3–4% for 10 names (to be measured on TRAIN-free history, i.e. on the control arms only, before the look), the SE over 68 months is about 0.4–0.5% and the **MDE at 80% power is about 1.2–1.4% per month**.
  - Published Indian momentum premia are of that order for long-short portfolios, but smaller for long-only versus matched controls.
- **Expected verdict:** UNPROVEN is likely, though not certain. E3 can detect a large monthly effect; it cannot detect a small one.

## 8. Assumptions and risks (explicit)

| # | Assumption / risk | Handling |
|---|---|---|
| A-1 | Pre-2025-09 prices rely on the **vendor's** split/bonus adjustment, which cannot be checked against our own corporate-action data | The §5 mask catches residual jumps; the result is labelled VENDOR-BASIS; a sensitivity on 2025-10 onward is reported, but it is too short to gate |
| A-2 | **Survivorship:** the current master only, and 2020 has 1,693 names versus 3,573 today | Momentum long-only is biased upward; C2 is also drawn from survivors, which partly cancels; report the bias direction and the universe size per year; a price ≥ ₹20 and top-500 liquidity filter limits it |
| A-3 | Knowability is assumed (as-if-live) for history | Forward confirmation is STRICT, from the daily pipeline |
| A-4 | Execution at the official open (auction), with a 5 bps fallback half-spread | Spread sensitivities of 3.63 and 9.34 bps; slippage sweep |
| A-5 | Monthly turnover is an estimate until measured | It is measured in the result; costs come from actual trades |
| A-6 | 68 months is a modest sample | The power section; no claim from an UNPROVEN |

## 9. Implementation plan (each step needs approval; nothing below is done)

1. **Code + synthetic tests:**
   - `app/training/e3.py`: monthly formation, signals from bars, netted monthly book, mask;
   - reuse `e2` costs, controls, the studentized CI and `candidate_status`;
   - a monthly null calibration script;
   - a runner with the one-look ledger.
   - No production run.
2. **Data:** `label-mon1-v1-vendor`, monthly open-to-open labels on the vendor basis at a recorded cutoff (append-only, deterministic, backup first). It needs a production-write approval.
3. **Calibration:** 1,000 + 1,000 null worlds, with the pre-set criteria.
4. **The single test look** (K = 10 primary; K = 20/30 and capital sensitivities reported).
5. **If ACCEPTED-EXPLORATORY:** a frozen forward paper-only confirmation on new months. It needs a shadow-log design and its own approval.

## 10. Decisions requested now

| # | Decision | Proposed |
|---|---|---|
| D1 | Predictors | P1 12-1 momentum, P2 52-week-high proximity |
| D2 | Primary K and capital | K = 10 at ₹10 L (₹1 L orders) |
| D3 | Vendor-basis assumption A-1 for pre-2025-09 prices | Accept, labelled VENDOR-BASIS |
| D4 | TEST window | 2021-01 → 2026-08 (about 68 months); the E1/E2 months reported excluded as a sensitivity |
| D5 | A3 unit | Calendar years (≥ 4 of 6) |
| D6 | Go-ahead for step 1 (code + synthetic tests only) | Your approval |
