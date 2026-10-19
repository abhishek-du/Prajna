# Stage 4 E4b: intraday bars (1h / 15m), pre-registration (APPROVED 2026-10-19; step 1 BUILT; NOT RUN)

**Status:** APPROVED 2026-10-19 (D1–D6, "haan sab decisions approve, step 1 shuru karo"). Step 1 (code + synthetic tests, `app/training/e4b.py`, `tests/training/test_e4b.py`) built; no production data read. No label, calibration or test look exists.
**Label:** research only. PAPER ONLY. No profitability claim.

**Written blind to outcomes.** Before this draft, the only 1h/15m data looked at was structural:
- the earliest session (2022-01-03 for both timeframes);
- bar start times and bar counts for one name (RELIANCE, March 2024).

No intraday return, signal or pick has been computed. Steps 1–3 (§9) must keep it that way until the single look.

**Parent design:** `docs/STAGE4_E4_INTRADAY_DESIGN_DRAFT.md`. It sets three things:
- E4b = opening-range / first-hour signals and target/stop exits;
- "no design choice for E4b may use E4a's test results";
- E4b has its own pre-registration.

§7 lists, honestly, where this draft cannot be blind to E4a.

## 0. Facts this design rests on

**Bars:**
- Upstox historical candles, vendor CA-adjusted, first observation stored (D3, revision-v4).
- The timestamp is the bar *start* in IST.
- A regular session has:
  - 25 15m bars (09:15 … 15:15, the last one 15:15–15:30);
  - 7 1h bars (09:15, 10:15, … 14:15, and 15:15, which is only 15 minutes long).

**Depth:**
- 1h: 2022-01-03 → today, complete (3,577 / 3,577 ACTIVE instruments).
- 15m: same depth; backfill in progress, expected complete ~2026-10-21.
- 1m: the last 92 days only.

**Non-regular sessions exist:**
- On 2024-03-02 (the Saturday DR session), RELIANCE has 15m bars only at 09:15–09:45 and 11:30–12:15.
- Muhurat sessions are also short.

**Price basis:**
- Every E4b return is a ratio of two prices from the **same session**, so a uniform per-day CA factor cancels.
- Only B3's gap (daily close d−1 vs open d) crosses a night. It uses the daily bars, exactly as E4a.
- B1's relative volume crosses sessions, hence the CA-window rule in §2.

**Costs:** MIS rates as `e4.MIS` (brokerage min(₹20, 0.06%), STT 0.025% sell, stamp, exchange, SEBI, GST), plus a half-spread of 5 bps per side.
- **Hurdle:** about 13–16 bps gross per session over the matched control at ₹1 L orders.

**Execution realism (2026-10-17, 15 sessions):**
- a market order after 09:15 and an exit at 15:15–15:20 sit about 0 bps from the official prices on average;
- the dispersion is large (p90 about +120 bps at the open).

## 1. Timing and the point-in-time rule (one convention)

| | Signal instant | Reads | Entry | Exit (primary) |
|---|---|---|---|---|
| **B1** (15m) | 09:30 | daily bars < d; the 09:15 15m bar of d | open of the 09:30 15m bar | open of the 15:15 15m bar |
| **B2** (1h) | 10:15 | daily bars < d; the 09:15 1h bar of d | open of the 10:15 1h bar | open of the 15:15 1h bar |
| **B3** (15m) | 09:15 | as E4a (open of d, daily bars < d) | official open of d (= E4a) | first target/stop touch on 15m bars, else open of the 15:15 15m bar |

- **The exit at 15:15 is primary.** It is a real, tradable instant before the broker's MIS square-off at about 15:20, and bars give it directly.
  - The official close is a **sensitivity** (reported only).
- **Missing bars:**
  - A missing entry bar means the trade did not fill: return 0, no cost, counted and reported.
  - The selection never requires a later bar to exist, because that would be look-ahead.
  - A missing exit bar falls back to the close of the last earlier bar of d.
- **Look-ahead tests (synthetic, as E1–E4a):**
  - changing any bar that starts at or after the signal instant leaves every pick unchanged;
  - for B3, changing any bar after the touch bar leaves the exit unchanged.

## 2. Universe, sessions, masks

**Sessions:**
- Only **regular full sessions**: NIFTY 50 (NSE_INDEX) has all 25 15m bars, 09:15 … 15:15.
- Special and Muhurat sessions are excluded and listed.

**Universe at the signal instant:**
- the E4a rule `e4.eligible` evaluated on daily bars (top 500 by 60-session median turnover at d−1, close(d−1) ≥ ₹50, history, no suspect session in the lookback, |gap(d)| ≤ 25%);
- **plus** the name has the bar(s) the signal reads.

**Masks (after selection, every arm, as E4a):**
- **Locked day:** a name locked on d (daily high == low) is dropped.
- **B1 CA window:** a name with any recorded corporate action whose ex-date lies in the 14 sessions before d, or on d, is not a B1 candidate. Relative volume across a split is unreliable even when the vendor adjusts.
- **Open consistency (data error):** |open of the 09:15 15m bar / official daily open − 1| > 1% marks (name, d) as a data error and excludes it before selection.
  - This is known at 09:15, so there is no look-ahead.
  - The rate is reported in the outcome-blind validation (§9 step 2).

## 3. Hypotheses (parameter-free: nothing fitted or searched)

All are long-only (E4 D2), with K = 10 at ₹10 L (₹1 L orders). K = 5 is a sensitivity.

| | Name | Score at the signal instant | Idea |
|---|---|---|---|
| **B1** | Opening-range breakout, "stocks in play" | Candidates: first 15m bar closed above its open (C₀₉₁₅ > O₀₉₁₅). Score: relative volume rv = V₀₉₁₅ / mean(V₀₉₁₅ over the previous 14 regular sessions; at least 10 present) | Names trading unusually heavily in the first 15 minutes, with buyers in control, keep moving the same way (Zarattini, Barbon & Aziz 2024 use a 5-minute ORB on high relative volume) |
| **B2** | First-hour momentum | m = C / O of the 09:15 1h bar − 1 (the gap is excluded) | The first hour's move continues for the rest of the day (intraday momentum, Gao, Han, Li & Zhou 2018, for the market. Here it is cross-sectional, an assumption to test) |
| **B3** | Gap fade with a target/stop exit | Picks = E4a P1 exactly (the 10 largest down-gaps). Target = entry × (1 + σ), stop = entry × (1 − σ); σ = `E3.volatility` at d−1 (daily return sd) | Does a symmetric 1σ target/stop beat the time exit for the same picks? |

**Direction is fixed in advance.** B1 and B2 are momentum. Their reversal is **not** tested, so there is no direction search.

**B3 touch resolution on 15m bars, from the 09:15 bar on:**
- The first bar whose high ≥ target or low ≤ stop decides.
- **If both are touched in the same bar, the stop counts** (pessimistic).
- The fill is at the level. If the bar opens beyond the level, the fill is at the bar's open.
- With no touch, the exit is the 15:15 bar open.

**Reported only (no gate):**
- B1 with a stop at the 09:15 bar low;
- B3 with 0.5σ and 1.5σ;
- B3's both-touch share;
- on the last 92 days, B3 resolved with 1m bars instead of the pessimistic rule.

## 4. Metric, controls, inference

**Unit: one session.**
- s_d = mean(pick return, entry → exit) − cost_d(picks) − mean(matched controls' return over the **same entry → exit instants**).
- B3's controls are held entry → 15:15, untraded (E2 PC-1a).

**Matched controls:** one random non-picked universe name per pick, from the same cell (`e4.matched_controls` with the third axis replaced):

| | Cell = turnover tercile × volatility tercile × … |
|---|---|
| B1 | first-bar return quintile (C₀₉₁₅/O₀₉₁₅ − 1) |
| B2 | first-hour return quintile |
| B3 | gap quintile (= E4a) |

- **Arms as E4a:** P, C2, PL (placebo), PLC, C0 (the random universe).
- **Unmatched picks are reported per session (step 1 finding, 2026-10-19).** B1 and B2 match on their own signal axis, so the top cells are depleted by the picks.
  - In an 80-name synthetic universe (45 cells), about 6.5 of 10 picks found no control and the placebo arm was biased under a strong planted momentum (+22 bps).
  - At 250 names, about 0.6 were unmatched and the placebo was clean (+1.7 ± 5.3 bps).
  - The real universe is 500. The look reports the unmatched rate, and step 2 reports it before the look. No rule is changed.
- **Inference: C2 from the start.** It is the inversion of the paired sign-flip randomization test (`e4.signflip_ci`, 10,000 fixed sign vectors). This is the method E4a found ADEQUATE; no bootstrap variant is tried.
- **Multiplicity:** Bonferroni over B1, B2, B3. Each CI is two-sided at **98.33%** (α = 0.05 / 3 per hypothesis).

**Gates (unchanged from E4a):**
- **A1:** the CI lower bound > 0, with NW (lag 19) reported;
- **A2:** s ≥ 0 at 1.5× costs;
- **A3:** positive in ≥ 3 of the 5 calendar years 2022–2026 (E4a had 4 of 6; the same ≥ 60% rule);
- **A4:** the placebo CI includes 0.

**B3's decision is a paired difference, not only A1–A4.**
- Δ_d = (B3 return − cost) − (the same picks held to 15:15 − cost), on the same picks and sessions.
- **Adopt** the 1σ target/stop for the paper pipeline (Stage 7–8) only if B3 passes A1–A4 **and** the 98.33% CI of Δ excludes 0 on the positive side.
- Otherwise the time exit stays, and any stop is a Stage 6 risk rule, not an edge claim.

**Power:**
- About 1,120 primary sessions, K = 10, a per-session sd of 0.8–1.2%.
- SE about 2.4–3.6 bps, so the **MDE is about 8–12 bps** at 98.33% with 80% power. That is below the 13–16 bps hurdle.

## 5. TEST window (single look)

- **Window:** 2022-01-03 … 2026-09-30, regular sessions.
  - B1 needs 14 prior sessions, so it starts around 2022-01-21.
  - The window ends at E4a's TEST end. Every session from 2026-10-01 belongs to the forward paper record and is never a research TEST session.
- **Primary population:** excludes 2026-07-22 … 09-30 (the disclosed paper-replay view of gap fade), for all three hypotheses, for uniformity.
- **Sensitivities (reported only):**
  - the full window;
  - the E1 period (2026-04-27 … 09-17) excluded;
  - K = 5;
  - slippage 5/10/20 bps per side;
  - the official close as the exit.

## 6. Calibration before the look (criterion fixed now)

**Null worlds for this design:**
- synthetic regular sessions of 25 15m bars (1h bars aggregated from them);
- 1,000 iid + 1,000 factor worlds (market and sector factors, t5 tails, log-vol AR(1) φ = 0.95, an intraday U-shaped volatility profile);
- new seeds (base 20261020);
- output `var/stage4/experiments/e4b/null_calibration.json`.

**Criterion (per hypothesis, every world type):**
- the Wilson 95% upper bound of `accepted` ≤ 1.67%; and
- the Wilson 95% interval of `ci_excludes_0` contains 1.67% (the Bonferroni level).

**If inadequate:** stop and report. **No alternative inference method is searched for E4b.**

## 7. Prior exposure (what is not blind, disclosed)

| Item | Seen before this draft | Consequence |
|---|---|---|
| E4a result: gap fade ACCEPTED-EXPLORATORY, +27.2 bps open → close, 2021-01 … 2026-09 | Yes | **B3 exists because of it.** B3's absolute result is not independent of E4a: same picks, same entry, same sessions. Its new question is only Δ (the exit), whose value has not been observed. |
| E4a gap-and-go FAIL | Yes | B1 and B2 do not use the gap. B2 excludes the gap by construction; B1 conditions on the first bar, not the gap. |
| Paper-replay view 2026-07-22 … 09-30 | Yes (gap fade) | Excluded from the primary population (§5) |
| Execution realism (15 sessions, 1m) | Yes | It set the 15:15 exit as primary and the half-spread unchanged. It used no intraday return of B1/B2. |
| Intraday returns 2022–2026 | **No** | This must hold until the look |

E4a's TEST sessions are reused, the same way E4a reused E1's period. B1's and B2's signals have never been computed on them.

## 8. Assumptions and risks

| # | Risk | Handling |
|---|---|---|
| B-1 | Vendor intraday vs daily mismatch (the community reports cases) | Open-consistency mask; the rate is reported before the look |
| B-2 | A bar's OHLC does not order the touches inside it | Pessimistic both-touch rule; 1m check on the last 92 days |
| B-3 | The 09:30 / 10:15 bar open is not a guaranteed fill | Slippage sweep; realism p90 about +120 bps at the open is a warning |
| B-4 | Survivorship (the universe from today's master) | As E4a A-2; report the direction |
| B-5 | Circuit / upper-band entries (B1, B2 buy strength) | Locked-day mask; report picks at the upper band |
| B-6 | Special and short sessions | Regular-session rule (§2) |

## 9. Implementation plan (each step separately approved)

1. **Code + synthetic tests:** `app/training/e4b.py`, pure, reusing `e4`. It covers the signals, intraday arm returns, B3 touch resolution, controls, the regular-session rule, masks and the look-ahead tests. **No production data is read.**
2. **Outcome-blind data validation (read-only, counts only):**
   - regular vs special sessions;
   - missing-bar rates by bar time;
   - open-consistency failures;
   - universe size per session.
   - No return, score or pick is computed.
3. **Calibration** (§6) on synthetic worlds only.
4. **The single E4b look:**
   - preconditions: the 15m backfill is 3,577 / 3,577, the Stage 1 gates PASS, and the calibration is ADEQUATE;
   - the config sha and confirmation string are recorded before the run;
   - B1, B2 and B3 run in one look. No hypothesis is looked at alone first.
5. **Results doc** and, only if B3's Δ rule adopts it, a proposal for the Stage 7–8 exit design.

## 10. Decisions requested

| # | Decision | Proposed |
|---|---|---|
| D1 | Hypotheses | B1 (ORB, relative volume), B2 (first-hour momentum), B3 (gap fade target/stop, disclosed as E4a-informed) |
| D2 | Primary exit time | 15:15 bar open; official close as a sensitivity |
| D3 | B3 levels and tie rule | Symmetric 1σ (daily vol at d−1); both-touch = stop first |
| D4 | TEST window | 2022-01-03 … 2026-09-30, the 07-22 … 09-30 view excluded |
| D5 | Multiplicity and gates | Bonferroni over 3 (98.33%), A1–A4, A3 at ≥ 3 of 5 years; B3 also needs Δ > 0 |
| D6 | Go-ahead for step 1 (code + synthetic tests only) | Your approval |
