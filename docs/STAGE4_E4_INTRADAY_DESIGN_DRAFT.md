# Stage 4 E4: intraday (same-day, MIS) selection, design draft (NOT APPROVED, NOT BUILT, NOT RUN)

**Status:** DRAFT, 2026-10-15. This is a design for review; no code, labels or test look exist.

**Why E4:**
- The user's strategy is **intraday: buy and sell the same day** ("Enter at pre-open or market open, exit based on target/stop or end of day").
- E2 and E3 were delivery designs. E3 is PAUSED.
- E1 *was* intraday (open → close), but it was never cost-evaluated with **intraday (MIS)** charges.

**Approved 2026-10-15:**
- Stage 4 focuses on intraday;
- the Stage 1 intraday backfill: 1h first (queued for tonight), then 15m;
- this design.

## 0. Facts this design rests on

### Intraday charges (Upstox charges API, 2026-10-13; `e2.Rates` MIS)

- Brokerage: min(₹20, 0.06%) per order.
- STT: 0.025% on the sell side only.
- Stamp duty: 0.003% buy.
- Exchange 0.00307% and SEBI 0.0001%, both sides.
- GST 18%.
- **No DP charge.**

| Order size | Intraday round trip | + 2 × 3.63 bps spread | Delivery (for comparison) |
|---|---|---|---|
| ₹10,000 | 17.7 bps | **25.0** | 100.3 |
| ₹50,000 | 13.0 | **20.3** | 43.7 |
| ₹1,00,000 | 8.3 | **15.6** | 36.6 |
| ₹2,00,000 | 5.9 | **13.2** | 33.1 |
| ₹5,00,000 | 4.5 | **11.8** | 31.0 |

**Hurdle:** a pick must earn about **13–16 bps gross per trade more than its matched control** at ₹1–2 L orders. E1's 1-session matched excess was 5–8 bps, so the E1 signals (reversal, ridge24) **would FAIL under MIS costs too**.

E4 must therefore test **different, intraday-specific signals**. A cheaper cost model alone does not rescue them.

### Data available by date

| Data | Range | Use |
|---|---|---|
| Daily OHLCV (open = the official opening price) | 2020-01 → today, about 1,685 sessions | **E4a:** gap signals with an open → close exit |
| 1h candles | from 2022-01 after the approved backfill (queued 2026-10-15, about 35 h over several nights) | **E4b:** opening-range / first-hour signals |
| 15m candles | from 2022-01 after the 15m backfill (after 1h) | **E4b:** finer entry, target/stop resolution |
| Pre-open order book (IEP, buy/sell quantities, depth) | **2026-09-24 onward only** (our capture) | **E4c later:** imbalance filters, once about 120+ sessions exist (about 5 months) |

**Historical pre-open:**
- The final IEP becomes the official open for pre-open-eligible stocks, so the **opening gap = open / previous close − 1 reconstructs the IEP gap from 2020**. This is a design assumption; verify it read-only on the 16 captured sessions before the look.
- Buy/sell imbalance and depth **cannot** be reconstructed from candles.

## 1. Timing and the point-in-time rule (one convention)

- **Signal instant:**
  - E4a: 09:15 IST, when the open is known. The final IEP is known at 09:08, but pre-open order entry is closed by then, so a pre-open order cannot use it.
  - E4b: the end of the opening window (09:30 for 15m, 10:15 for 1h).
- **Entry:**
  - E4a, daily data: the official open, plus half-spread and slippage, as an **assumption**. The auction price is not guaranteed to be fillable after 09:15. Sensitivities: slippage 5, 10 and 20 bps.
  - E4b: the open of the first bar after the signal instant (e.g. the 09:30 15m bar open).
- **Exit:** the official close (EOD) as the primary proxy. Brokers square off MIS positions at about 15:20, so the close is a proxy, and a 15:15-bar exit is the E4b sensitivity. Target/stop exits only in E4b, where 15m bars resolve the order of touches.
- **Look-ahead tests (synthetic, as in E1–E3):** changing any bar after the signal instant must leave every pick unchanged.

## 2. Hypotheses (parameter-free first: no fitting, no tuning)

**E4a (daily data, 2021 → 2026):**

| | Predictor | Score at 09:15 | Idea |
|---|---|---|---|
| **P1** | Gap fade | −gap, gap = open / prev close − 1 | Large gap-downs mean-revert during the day |
| **P2** | Gap-and-go | +gap, and only names whose prev-day volume > 1.5 × 20-day average | Strong, news-driven gap-ups continue |

- **Universe:** the top 500 by 60-session median turnover with a price ≥ ₹50, liquid enough for ₹1–2 L orders.
- **Selection:** the top **K = 10** (₹1 L orders at ₹10 L); K = 5 (₹2 L) as a sensitivity.
- **Long-only primary.** A short side (MIS allows intraday shorts) is a **separate decision**: it doubles the hypotheses, and short-sale constraints apply.
- **Data-quality mask:** E2 Amendment 3 and the E3 `suspect_sessions` rule. A gap > 25% with no recorded corporate action is not a signal, it is a data error.

**E4b (after the backfills): opening-range breakout and first-hour momentum, specified in its own pre-registration once the 1h/15m data exists.** No design choice for E4b may use E4a's test results.

## 3. Metric, controls and gates (same machinery as E2/E3)

- **Unit:** one session.
  - s_t = mean(pick open → close return) − cost_t(picks) − mean(matched controls' open → close return);
  - controls are untraded (PC-1a), matched by turnover decile × volatility decile **and gap decile** (otherwise gap fade would "beat" controls just by holding gap-down names).
- **Inference:** the studentized block bootstrap (block 5 sessions) with Newey-West (lag 4), 97.5% two-sided (Bonferroni over P1/P2). A new 1,000 + 1,000-world null calibration is required before the look (E2 §6 criteria).
- **Gates:**
  - **A1:** the CI lower bound > 0 with NW agreement;
  - **A2:** s ≥ 0 at 1.5× costs;
  - **A3:** positive in ≥ 4 of 6 calendar years;
  - **A4:** the placebo CI includes 0;
  - **A5:** P2 > P1 is not needed, since they are independent hypotheses; both are reported.
- **TEST:** 2021-01 → 2026-09, about 1,400 sessions, a single look.
  - Sessions already used by E1 (2026-04-27 → 09-17) are reported **excluded** as a sensitivity.
  - The signals differ from E1's, but that period has been seen.
- **Power:** about 1,400 sessions with K = 10 per session. With a per-session sd of 0.8–1.2% for 10 names, the SE is about 0.02–0.03% and the **MDE is about 7–9 bps per session**. That is **below the 13–16 bps hurdle**, so E4a can confirm or reject a cost-clearing edge, unlike E2.

## 4. Assumptions and risks

| # | Risk | Handling |
|---|---|---|
| A-1 | Pre-2025-09 prices are the vendor's adjustment (as E3 A-1) | Mask; VENDOR-BASIS label |
| A-2 | Survivorship (1,693 names in 2020 vs 3,573 now) | Liquidity universe; report the direction |
| A-3 | Entry at the official open is an approximation for daily data | Slippage sweep; E4b uses real post-open bars |
| A-4 | The close vs the about 15:20 MIS square-off | E4b sensitivity with the 15:15 bar |
| A-5 | Circuit limits / no-trade days (a stock locked at its band) | Exclude names whose open equals the day's high and low at a band (to define) |
| A-6 | Leverage (MIS margin) is out of scope | Notional = capital; leverage belongs to Stage 6 risk |

## 5. Implementation plan (each step separately approved)

1. Code + synthetic tests (`app/training/e4.py`): gap signals, matched controls including gap deciles, the session book with MIS costs, mask, inference reuse. **No production run.**
2. Labels `label-intraday-oc-v1`: open → close per session, from daily bars on the vendor basis, at a recorded cutoff. Append-only, backup first.
3. Calibration: null worlds for this design.
4. The single E4a test look.
5. E4b pre-registration once the 1h/15m backfill completes.

## 6. Decisions requested

| # | Decision | Proposed |
|---|---|---|
| D1 | Predictors | P1 gap fade, P2 gap-and-go (volume-filtered) |
| D2 | Long-only primary; short side later as its own experiment | Yes |
| D3 | K and capital | K = 10 at ₹10 L (₹1 L orders); K = 5 sensitivity |
| D4 | Entry assumption for daily data | Official open + half-spread; slippage 5/10/20 bps sensitivity |
| D5 | TEST window | 2021-01 → 2026-09; E1 period excluded as a sensitivity |
| D6 | Go-ahead for step 1 (code + synthetic tests only) | Your approval |
