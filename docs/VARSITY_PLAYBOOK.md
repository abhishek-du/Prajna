# Prajna trading playbook: Zerodha Varsity distilled

Source: every module the user downloaded was read in full:
- Modules 1–11, 13 and 14;
- the Sector Analysis articles;
- the Social Stock Exchange articles;
- all 604 Innerworth "Mind over Markets" articles.

Line-level working notes, with quantified rules and a "Prajna mapping" per section, are in `backend/var/research/varsity/varsity_notes.md` (local only, gitignored: the repo is public and the notes paraphrase copyrighted Varsity/Innerworth text).
This playbook is the guided version: how to build a strategy, how to size and protect it, what to do in each market situation, and how to tell a real edge from luck.
Date: 2026-10-26. Companion design: `docs/STAGE4_AI_AGENT_DESIGN.md`.

> Ground truth first. Varsity promises no strategy that wins in every situation, and nobody can. What it teaches is a **process**: positive expectancy plus strict risk control plus discipline, surviving long enough for the edge to show. Prajna's own evidence (E1–E5, E5-H) shows that edges in liquid Indian large caps after costs are small. Every rule below is either a **risk rule**, used as is, or a **hypothesis**, which must pass a pre-registered test before it gets capital.

---

## 1. Ten laws (the non-negotiables)

1. **Survival first.**
   - A loss L needs a gain of L/(1−L) to recover: −10 % → +11.1 %, −25 % → +33 %, −50 % → +100 %, −60 % → +150 %.
   - Risk ≤ 1–2 % of equity per trade, with an open-risk cap of about 3 % and a cash reserve.
   - Never martingale: no doubling down, no averaging a loser, no size-up to "win back" (Varsity M9; Amaranth; Sumitomo; Leeson/Barings).
2. **Expectancy, not hit rate.**
   - E = p·W − (1−p)·L, net of all costs.
   - With a 40 % hit rate you need W/L > 1.5. "Win as few as 4 of 12 and still come out ahead."
   - Judge payoff ratio and expectancy, never win % alone.
3. **Every trade has four parts before entry:** entry, stop, target and holding period (M2 ch 1). No plan means no trade. RRR = (target − entry)/(entry − stop) ≥ 1.5.
4. **The stop is set at entry and only tightens.**
   - It is placed outside noise: ≥ 1 ATR, or σ_daily·√hold_days.
   - If the RRR fails with a proper stop, skip the trade. Never tighten the stop into noise to keep the share count (Innerworth #553).
   - Cut losers immediately (Douglas: "execute losing trades immediately upon the perception that they exist"). Let winners run per plan, because profit-taking too early is the disposition effect.
5. **Size is decided by risk, not conviction.** qty = (risk% × equity) / (entry − stop), scaled by volatility. Conviction may scale size only through a proven, out-of-sample calibration such as fractional Kelly with W and R from out-of-sample data; until then, never.
6. **Costs and slippage are part of the strategy.**
   - Barber & Odean: 250 % turnover against 2.4 % turnover gave the same 18.7 % gross but 11.4 % against 18.5 % net.
   - Prajna's gap fade: +27 bps at the base cost, +7 bps at 10 bps/side, negative at 20.
   - Model name-specific impact. Prefer limit orders. Avoid illiquid names and the first minutes for any strategy that is not about the open.
7. **No daily P&L target.** Earl's "$400/day" drives overtrading and poor setups. "Let the market tell you how much it will give you." Stand-aside days are decisions.
8. **Regime decides the tool.** Trend tools (MA, MACD, Supertrend, breakouts) work in trends and bleed in ranges. Range tools (RSI extremes, Bollinger, VWAP reversion) work in ranges and fail in trends. Detect the regime first (ADX, breadth, MTF alignment); otherwise stand aside.
9. **History repeats only when it does.** Every pattern, seasonality, correlation and "conventional wisdom" is conditional and non-stationary. Correlations go on returns, never prices. Test against a placebo, walk forward, and keep wide error bars. The Holt-Winters result on USDINR found no seasonality: "it always falls before X" is noise until tested.
10. **Journal everything and be brutally honest.**
    - Track plan adherence. A profitable deviation is an *unjustified win*; a loss with the plan followed is a *justified loss*.
    - Self-serving attribution ("wins = my skill, losses = the broker") is the default human bias, and the journal is its antidote.

---

## 2. The process: from idea to capital

```
POV / idea  →  hypothesis  →  system spec  →  test  →  paper forward  →  (authorised) small live  →  scale by gates
```

1. **POV (M1, M3, M2).** Ideas come from fundamentals (FA), technicals (TA), quantitative work (QA: "P/E at +3σ", "ratio at −2.5σ") or events (results versus expectation). They never come from tips or TV: "Don't trust anything you read or hear; test it yourself."
2. **Hypothesis.** State it in one sentence as a conditional expectation: *given factor set X, outcome Y over horizon H is better than control*. Varsity's own definition of TA is "history repeats given the same factors".
3. **System spec (M10).** Defined logic, inputs, interpretable output and a trade/no-trade decision. It includes the regime tags, universe, entry, stop, target, time stop, size rule and cost model. "Decide the logic once, then follow it." If a rule cannot be written down, it is not a system (gut feel and "systematic deduction" do not count).
4. **Test (Prajna doctrine, confirmed by Varsity and Innerworth):**
   - pre-register the hypothesis, metric, gates, MDE and windows;
   - walk-forward out of sample;
   - placebo or permutation null;
   - a limited parameter search;
   - one look;
   - backtest **per side and per contract**: the SBIN calendar spread worked only on the short side, so trade only the side that works;
   - beware unrepresentative samples and the law of large numbers misapplied to small samples.
5. **Paper forward.**
   - Expect live results below the backtest (a live-versus-backtest haircut).
   - Pre-register the minimum sample.
   - One strategy change per forward window, with no strategy-hopping.
6. **Small live (only with explicit written authorisation; Prajna is paper-only today).**
   - Start at the minimum size and scale 10 → 25 → 50 → 100 %, gate by gate.
   - Traders who skipped this "tuition" phase blew out (Innerworth: "taking the plunge", "slow easy steps").
7. **Monitor for edge decay.**
   - "After one strategy is discovered, it stops working."
   - Arbitrage edges are competed to zero (M6 fish market).
   - Rolling-window statistics trigger shadow mode and re-validation.

---

## 3. Risk and money management: the exact rules

| Item | Rule | Source |
|---|---|---|
| Equity model | **Reduced total equity** = core equity + only locked-in profit (protected by a trailing stop) | M9 ch 12 (Van Tharp) |
| Per-trade risk | 1 % default (professionals 1–3 %); qty = risk ₹ / (entry − stop) | M9 ch 14 |
| Volatility sizing | shares = (k% × equity) / ATR(14), so each position carries equal volatility; cap total portfolio volatility exposure | M9 ch 13 |
| Kelly | K = W − (1−W)/R; use only **fractional** Kelly scaled into a per-trade cap (K × 5 % cap); W and R from out-of-sample data | M9 ch 14 |
| Stop distance | ≥ 1 ATR; or entry × (1 − σ_d·√days) | M2 ch 20; M5 ch 19 |
| Portfolio | ~10–15 names maximum for diversification (unsystematic risk flattens around 20); hedge systematic risk with index futures (β-weighted) | M9 ch 1–5; M4 ch 11 |
| Correlation | compute σp = √(wσᵀ·Corr·wσ) each morning; prefer low correlation; sector cap 3 | M9 ch 5 |
| Daily report | "4:15 report": VaR/CVaR (historical, ≥ 1 y), exposure, concentration | M9 ch 10 |
| Leverage | ≤ ~1:10; loss = 1/leverage wipes the margin | M4 ch 3 |
| Daily loss limit | hit → halt for the session; no revenge | Innerworth (many) |
| Drawdown | size down after threshold X, halt after Y; never size up after losses or streaks | M9 ch 11; Innerworth |
| Trades per day | capped; self-control depletes with each decision (Muraven) | Innerworth #528 |
| Capital buckets (personal finance) | e.g. long-term core + satellite trading; ≤ 35 % of the trading bucket per strategy | M5 ch 19; M3 ch 1 |
| Infra risk | broker-side SL/bracket; system down → flatten; partial-fill rules; backup connectivity | Innerworth #501, #575 |

---

## 4. Trade construction checklist (the Varsity 6 points, made testable)

For a technical swing or intraday setup (M2 ch 18–19), score each candidate:

1. **Recognisable pattern** with its precondition (a bullish pattern needs a prior downtrend). A pattern without its prior-trend condition is not a pattern.
2. **Stop near support/resistance.** Use a time-tested zone: ≥ 3 touches, spaced ≥ 2 weeks apart, look-back 3–6 months for short-term trades and 12–18 months for swings. The stop should be within ~4 % of S&R, otherwise reject.
3. **Volume ≥ 10-day average** on the signal bar. Price↑ with volume↓ is a bull trap; price↓ with volume↓ is a bear trap.
4. **Dow view:** the primary and secondary trend agree, the indices confirm (Nifty, midcap and smallcap), or there is a breakout, range, flag or double top/bottom context.
5. **Indicators** (RSI, MACD, ADX) confirm → **size up**; otherwise trade **smaller**. Points 1–3 are near-mandatory, and indicators only modulate size.
6. **RRR ≥ 1.5** with the S&R target and a properly placed stop.

Trade only when ≥ 4 points pass. A weaker pattern with more points beats a stronger pattern with fewer.

**Modifiers:**
- multi-timeframe alignment (monthly → weekly → daily → 60/15 minutes): mixed signals mean indecision, so avoid;
- the higher timeframe is more reliable;
- under indecision (doji or spinning top), use half size;
- a true breakout needs **high volume and momentum after the break**; the stop is the broken level, and the minimum target is the range width projected from the breakout;
- after a pattern-day close, the risk-taker enters near the close and the risk-averse waits for confirmation. These are different strategies and must be tested separately.
- After entry, do nothing except trail the stop.

---

## 5. Situation playbook: what to do in each market state

Each row is the default action. Strategy cells marked *(hypothesis)* trade only once tested.

| Situation (how to detect) | What tends to work | What to avoid | Risk action |
|---|---|---|---|
| **Broad uptrend**: index > 50-EMA, ADX ≥ 25, breadth > 60 % above 50-DMA, indices agree | trend continuation, breakouts with volume, buying pullbacks to EMA or Fib 38–62 % *(hypothesis)*; RSI stuck > 70 = strength, not a short | shorting "overbought"; fading strong gap-ups with news | normal size; trail stops |
| **Broad downtrend**: mirror of the above | short continuation intraday (spot shorts are intraday only); avoid "falling-quality" catches without price confirmation | long momentum portfolios (they bleed **more** than the market in downtrends, M10 ch 16) | reduce gross; hedge |
| **Range / sideways**: ADX < 20, flat EMAs, price between tested S&R | buy near support / sell near resistance with a candle confirmation; VWAP / Bollinger reversion *(hypothesis)*; short strangles outside the range (options; not in Prajna scope) | MA crossovers (whipsaw), breakout chasing without volume | smaller size; quick time stops ("should work almost immediately") |
| **Volatility shock / crash day**: VIX spike, gap ≥ 2σ, breadth collapse | stand aside or minimum size; let stops work; "close to regain objectivity" | averaging down; widening stops; new mean-reversion entries in free-fall | cut gross; halt on the daily limit; no overnight |
| **Low-volatility compression**: range contraction, VIX at a low percentile | wait for a breakout with volume; flag continuation (≥ 5–10 % rally then a 3 % low-volume pullback) *(hypothesis)* | over-trading tiny ranges (costs dominate) | normal; fewer trades |
| **Pre-event wait**: RBI policy, Budget, results, FOMC, expiry | "When in confusion, do nothing" (Brexit); markets drift sideways before events and IV inflates | directional bets just before the binary event; long straddles bought at high IV | event gate: reduced size or stand aside; no position across results |
| **Post-results / news reaction** | results surprise versus expectation drives drift (E6 rule, frozen monitor); "markets react to bad news first when given both" | trading the headline direction alone; in-line results with no surprise (negative bias) | event-specific strategy only |
| **Gap open, no news** | fade noise gaps (gap fade, ACCEPTED-EXPLORATORY) | fading gaps that have news or results (that is information, not noise) | slippage-aware entries; small size |
| **Gap open with material news** | gap-and-go is unproven (E4: FAIL); stand aside or event study first | fading it | — |
| **Sector move led by index heavyweights** | laggards in the same sector catch up later *(hypothesis, Innerworth #600)* | chasing the leader late | — |
| **Macro move (crude, USDINR, global)** | sector see-saw: crude↑ hurts OMCs and helps upstream; INR↓ helps IT exporters *(conditional hypotheses)*; gold up = risk-off | treating these as fixed laws | — |
| **Illiquid or circuit-band stock** | nothing intraday | market orders; illiquid names (impact cost, operator activity) | universe filter: liquid only |
| **Data or system degraded**: Stage 1/2 not green, stale features, vendor down | no new entries | "trading through it" | flatten on loss of protection |
| **Losing streak** (K losses, rolling expectancy breach) | first ask whether the market condition changed (Simon v. Jake); check the regime, breadth and dispersion; size down; re-test small | revenge, size-up, rewriting the strategy mid-window | rule-based de-risk → shadow |
| **Winning streak** | keep the same risk; expect mean reversion of luck | raising size or frequency (Barber & Odean overconfidence) | unchanged size |
| **Strategy decay**: rolling CI of net expectancy below its floor | move the strategy to shadow; diagnose what changed; re-validate on new data | sunk-cost loyalty to the old method | size 0 until re-accepted |
| **Year-end / holiday sessions** | stand aside more (thin markets, tax-loss selling) | assuming normal behaviour | reduced |

---

## 6. Strategy families from Varsity, and their Prajna status

| Family | Core rule (from Varsity) | Prajna fit |
|---|---|---|
| Candlestick + S&R swing | 6-point checklist (§4); entry at the pattern close or on confirmation; stop at the pattern extreme | intraday version testable on 15-minute bars; swing needs positional scope |
| MA / Supertrend trend following | price > 50 EMA, or a 9×21 / 25×50 crossover; **take every signal** (you cannot tell the one big winner in advance) | regime-gated CANDIDATE |
| Breakout with volume (Dow) | high volume + momentum after the break; stop = the level; target = range width | CANDIDATE; add a breadth gate |
| Range reversion (RSI / BB / VWAP) | buy the lower band, target the middle; exit if not working quickly | CANDIDATE in the range regime |
| ADX / DI system | ADX ≥ 25 and a +DI/−DI cross; stop at the signal-candle extreme | regime feature first |
| Gap fade | fade noise-driven gaps (no news, not results) | ACCEPTED-EXPLORATORY (E4) |
| Earnings surprise drift | beat → up, miss → down, in-line → flat with a negative bias | E6 frozen monitor (look ~Apr 2027) |
| Pair trading (cointegration) | regress prices (200 days), lowest error ratio, ADF p ≤ 0.05 re-checked every 15–20 days; z = ±2.5 entry, ±1 target, ±3 stop; β-neutral; reject a large intercept | strong statistical candidate; **positional** (NRML), outside today's MIS scope |
| Momentum portfolio | rank 150–200 liquid names by 12-month return, top 10–15, monthly rebalance; **needs a regime filter** | positional; outside MIS scope |
| Calendar spread | next − current future versus the 200-day mean ± 1σ; trade only the side that backtests | derivatives; outside scope |
| Option writing (σ strikes) | write ≥ 1–2σ OTM calls, ≤ 15 days left, avoid writing puts ("panic spreads faster than greed"), exit at ATM; the tail risk ("eat like a chicken…") | not Prajna scope |
| Pre-event IV crush | sell the ATM straddle a few days before, exit just before the announcement; never buy straddles into events | not Prajna scope; but the "pre-event compression" equity feature is testable |
| Fundamental quality filter | RoE > 20–25 % with low debt, CFO > 0, receivables not driving sales, few subsidiaries, no governance red flags; Nifty P/E bands (> 22 caution, ≤ 16 attractive) | universe and regime context, not intraday signals |

---

## 7. Fundamentals in a trading system

- FA picks and TA times. A great stock can go nowhere for years, so trade it meanwhile.
- Governance red flags mean exclusion regardless of P&L. The flags:
  - related-party transactions;
  - large "other income";
  - promoter dealing;
  - subsidiary maze;
  - frequent accounting-policy changes.
- Earnings quality: profits rising without sales and cash flow is a red flag; cash flow tells the truth.
- Sector KPIs matter on results days:
  - banks: NIM, GNPA/NNPA, PCR, CASA, CAR;
  - IT: constant-currency growth, TCV, attrition;
  - autos: monthly volumes;
  - hotels: RevPAR;
  - retail: same-store sales;
  - real estate: collections, QTS.
- Use them to judge a *surprise versus expectation*, not as intraday signals.
- Market regime: Nifty P/E above 22 warns; ≤ 16 is attractive. Index valuation is slow context, not timing.

---

## 8. Psychology turned into system rules (the 604 Innerworth articles in 20 lines)

1. A detailed plan is the safety net: entry, adverse-signal list, exit, size. Most discipline failures come from plans that are not detailed enough.
2. Think in probabilities. A single trade is one of hundreds, and that is only true if risk per trade is small.
3. Process goals over outcome goals. Count justified wins and plan adherence; look at money monthly.
4. Stand aside when you, meaning the system, are not at your best (data or infra not green), or when the market does not fit the method.
5. Overconfidence after wins and revenge after losses are the two killers. Keep size constant and keep the daily halt.
6. Overtrading, from boredom, sensation-seeking or the "real traders trade all day" belief, destroys net returns.
7. Two-stage belief (Gilbert): run the devil's-advocate stage before every trade, especially under time pressure.
8. Mood biases probability estimates. Generate ideas optimistically, tear them down pessimistically, execute mechanically.
9. Sunk cost: research effort does not oblige a trade, and a failed hypothesis is closed (as E4b and E5-H were).
10. Image and mere-exposure bias: company image predicted forecasts but not returns (MacGregor). News "hype" is not evidence.
11. The representativeness heuristic: a good company is not a good trade. Peak earnings regress.
12. Hot-sector and false-consensus bias: sector news does not lift every stock equally.
13. Prices are opinion with a standard error. Situations explain only about 16 % of behaviour (Funder & Ozer), so patterns are probabilistic.
14. Testing intuition: every decision must list the evidence it used. No evidence means an unfounded hunch, so discard it.
15. Losing streaks: attribute to specific, changeable causes (the regime, the method), never to "I'm incompetent". Diagnose before changing.
16. Never hide losses or "save face" (Leeson). Reconcile daily.
17. Self-control depletes. Cap the number of decisions, rest, and use automated exits.
18. Accept the uncontrollables: analyst talk, global events, slippage, outages. Plan the responses in advance.
19. Learning goals, small steps, consistency first: constant risk, the same conditions, the same preparation.
20. "Know when to walk away": stop trading a method that lost its edge, diagnose, re-test small.

---

## 9. Evaluation and reporting standards

- Net of **all** costs: brokerage, STT, exchange charges, GST, stamp duty, slippage and impact.
- **Rolling-window** statistics (min, average and maximum), never a single point-to-point backtest (M11).
- Report:
  - expectancy, payoff ratio and hit rate;
  - Sharpe and Sortino of session returns;
  - max drawdown and its duration;
  - up/down capture against bench_c0;
  - turnover and cost drag;
  - plan adherence.
- Significance: a bootstrap or sign-flip CI on session returns; luck tests (placebo); state the MDE before looking.
- Publish every metric's formula. Any headline metric can be gamed by its definition: an insurer's claim-settlement ratio is the M14 lesson.
- Capacity and crowding: watch edge shrinkage as turnover or size grows (M11 fund capacity; M6 arbitrage competition).

---

## 10. Operations playbook (adverse events written in advance)

| Event | Pre-written response |
|---|---|
| Broker/API or data vendor down | no new entries; protection check; flatten if protection cannot be verified |
| Stage 1/2 gate red, stale features | no entries that session; run the incident runbook |
| Partial fill | per-strategy rule: complete within N minutes, or cancel the remainder and size the stop to the filled quantity |
| Circuit hit / trading halt in a held name | exit at first opportunity; mark it as an incident in the journal |
| Results or board meeting discovered after entry | exit before the event window unless the strategy targets it |
| Gap through the stop | exit at market open; record the slippage against the model |
| Daily loss limit hit | halt; no override without a logged reason and a delay (cooling-off) |
| "Ego shock" (sudden large adverse move) | emergency procedure: flatten to cap, then review offline |

---

## 11. What Prajna will not do

- Trade live without explicit written authorisation. It is paper only today.
- Average down, martingale, or size up after streaks.
- Trade on tips, TV, social media or unverified "AI hunches" without evidence ids.
- Fit parameters on, or replay inside, a research TEST window, or peek at a forward test before its look.
- Use an LLM signal in a historical backtest. Its pre-training leaks the future, so LLM features are validated forward only.
- Bypass the Stage 1 gates, the risk caps or the event gates.
- Chase "a strategy that works in every situation". It does not exist, and searching for it is the Holy-Grail trap.
