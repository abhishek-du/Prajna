# Stage 4 v2, phase P1: regime engine + shadow strategy library (pre-registration v2.3, FROZEN)

**Status: FROZEN 2026-10-26 (policy `p1-shadow-v1`). Forward start: 2026-10-27, the first trading session after the freeze. Code: `backend/app/shadow/`, migrations 0027 + 0028. v2.3 runs every strategy in a core and a strict variant (§1b). The user approved the four PRAJNA DEFAULT values and the 21:30 cron line on 2026-10-26.**

**Parents:**
- `docs/STAGE4_AI_AGENT_DESIGN.md` (L0–L3, L5, L7);
- `docs/STAGE4_AGENTIC_INFRA.md` (the agent roles; P1 is its first block);
- `docs/VARSITY_PLAYBOOK.md` (the doctrine).

**User decisions on 2026-10-26:**
- start P1 with the two recommended CANDIDATE strategies;
- **take every number from the playbook and the design doc.**

v2 replaces the v1 draft's own choices with those numbers. §1 lists the source of every number. Where neither document gives one, the existing Prajna paper limit (`app/paper/risk.py`) is used, or it is marked **PRAJNA DEFAULT**.

## 1. Number sources

| Parameter | Value | Source |
|---|---|---|
| Per-trade risk | 1 % of reduced total equity | Playbook §3 (M9 ch 14); Design L0 |
| Open risk cap | ≤ 3 % → at most 3 open trades at 1 % each | Playbook law 1; Design L0 |
| Max positions / sector cap | 10 / 3 names per sector | Design L0; Playbook §3; `risk.py` |
| Daily loss limit | −3 % of capital (= −3R) → halt for the session | `risk.py` `daily_loss_halt` (Design L0 gives no number) |
| Drawdown protocol | 5 % → half size; 10 % → halt until review | 10 %: `risk.py` `max_drawdown_halt`; 5 %: **PRAJNA DEFAULT** (Design L0 "X %") |
| Stop distance | ≥ 1 ATR(14); stop set at entry, only tightens | Playbook law 4, §3 |
| RRR | ≥ **2.0**, else skip (Varsity minimum 1.5; the user chose 1:2 on 2026-10-26) | USER; Playbook law 3 |
| Size | qty = risk ₹ / \|entry − stop\| | Playbook law 5, §3 |
| Checklist | trade only if ≥ 4 of the 6 points pass; indicators confirm → full size, else half | Playbook §4 |
| Volume confirmation | signal-bar volume ≥ 10-day average | Playbook §4 point 3 |
| Breakout stop / target | stop = the broken level (at least 1 ATR); minimum target = the range width projected from the breakout | Playbook §4 modifiers, §6 |
| Range reversion | buy the lower Bollinger band (20, 2σ), target the middle band; RSI 30/70; exit if not working quickly | Playbook §5, §6 (M2) |
| Trend regime | index > 50-EMA, ADX ≥ 25, breadth > 60 % above 50-DMA, indices agree | Playbook §5 row 1 |
| Down regime | the mirror: index < 50-EMA, ADX ≥ 25, breadth < 40 %, indices agree | Playbook §5 row 2 |
| Range regime | ADX < 20 | Playbook §5 row 3; Design L1 |
| Volatility shock | VIX spike, index gap ≥ 2σ, breadth collapse | Playbook §5 row 4 |
| Pre-event | RBI policy, Budget, results, FOMC night, F&O expiry → reduced size or stand aside | Playbook §5 row 6; Design L0 event gate |
| Year-end / holiday | reduced size | Playbook §5 last row |
| Liquidity | ₹5 cr median daily turnover; price ≥ ₹50; E4 top-500 universe | `risk.py`; `app.training.e4` |
| Checkpoints | pre-open, 09:30, 10:30, 12:00, 13:30 | Design L2 |
| "Not working" time stop | 4 × 15m bars (1 h) | **PRAJNA DEFAULT** (the playbook says "should work almost immediately") |
| VIX spike threshold | VIX T−1 percentile in the last 252 sessions ≥ 90, or a 1-day VIX change ≥ +20 % | **PRAJNA DEFAULT** (the playbook gives no number) |
| Breadth collapse | `ad_ratio` ≤ 0.2 | **PRAJNA DEFAULT** |
| Opening range | the first 15m bar, 09:15–09:30 | **PRAJNA DEFAULT** (data granularity) |
| No-news proxy for reversion | \|return from the T−1 close\| < 3 % | **PRAJNA DEFAULT**. News-AI is forward-only and not yet validated, so it is not used in P1. |
| Slippage | 0 bps primary; 5, 10 and 20 bps sensitivity | Playbook law 6 (gap fade fragility) |

The **PRAJNA DEFAULT** rows are the only judgement calls. The user may change them before the freeze, and never after.

## 1a. User additions (2026-10-26, from the manager discussion checklist)

| # | Rule | Applies to | Exact definition | Skip reason |
|---|---|---|---|---|
| 1 | F&O stocks only | S1, S2, placebos | the universe ∩ stocks with NSE futures in the latest Upstox instrument master stored before 09:15 of T (about 204–213 names). The regime breadth still uses the full universe | (not in the pool) |
| 2 | Reward : risk ≥ 1 : 2 | S1, S2 | `rrr_min` 2.0 | `SKIP_RRR` |
| 3 | Candlestick confirmation | S1: the breakout bar is a strong candle (body ≥ 50 % of its range, close in the top / bottom 25 %). S2: the signal bar is a hammer / shooting star (wick ≥ 2 × body, the other wick ≤ body) or a bullish / bearish engulfing of the previous bar | signal condition (no candle, no signal) | — |
| 4 | Support/resistance zones | daily pivots (5-session extremes) over the last 120 sessions ≤ T−1, clustered within 1 %; a zone needs ≥ 3 touches spanning ≥ 10 sessions (Playbook §4 point 2) | S1: a zone strictly between the entry and the target blocks the trade. S2: needs a zone within 1.5 % of the signal close | `SR_BLOCKED`, `NO_SR_ZONE` |
| 5 | No new entry after the first stop-loss of the day | each strategy book | after the first STOP / STOP_GAP exit, entries at or after that time are skipped | `HALT_FIRST_STOP` |
| 6 | MA / MACD | S1: EMA 9 above EMA 21 on 15m bars (below for shorts) is a signal condition; MACD(12, 26, 9) line above its trigger joins point 5 (full size). S2: point 5 needs RSI < 25 (> 75) **and** the MACD histogram turning up (down) | — | — |
| 7 | Volatility cap for S1 | the stock's daily ATR(14) / previous close ≤ 3 % | S1 | `VOL_TOO_HIGH` |

**Consequence, stated before the freeze.** On the three mechanics sessions (counts only, no P&L), S1 took 0–3 trades per session and S2 took 0, against 3 and 14 per session before these additions. At that rate the 60-session look will have very few trades, especially for S2, and can only detect large effects. The 250-session look may still be underpowered for S2.

## 1b. Variants (user decision 2026-10-26: "core dono chalao")

Each strategy runs in two variants on the same sessions, each with its own book, guards and placebo:

| Variant | Rules |
|---|---|
| `orb_breadth_core_v1`, `vwap_revert_core_v1` | §1 only (the Varsity numbers): the whole stock universe, RRR ≥ 1.5, no candle / S/R / EMA 9/21 / MACD / volatility-cap / first-stop rules |
| `orb_breadth_strict_v1`, `vwap_revert_strict_v1` | §1 + all seven §1a rules: F&O stocks only, RRR ≥ 2.0, the candle confirmations, the S/R rules, EMA 9/21 + MACD, the S1 daily ATR ≤ 3 % cap, and no new entry after the first stop-loss |

The hypotheses in §7 apply to each variant.

**H5 (does the checklist add value).** For each strategy, compare the strict variant with the core variant:
- net R per trade;
- net bps per session, where a session with no trade counts as 0;
- max drawdown.

**Multiplicity.** At the 250-session look, four variants are judged, so each variant's CI is Bonferroni-adjusted: 98.75 % instead of 95 %. The 60-session look keeps its 99.5 % CI.

**Mechanics smoke (counts only, no P&L)**, trades per session on 2026-08-05 / 09-02 / 10-07:

| Variant | 08-05 | 09-02 | 10-07 |
|---|---|---|---|
| S1 core | 0 | 3 | 3 |
| S1 strict | 0 | 3 | 2 |
| S2 core | 14 | 11 | 14 |
| S2 strict | 0 | 0 | 0 |

There were 0 violations.

## 2. What P1 is, and what it is not

- **It is** a daily, after-the-close **shadow** run:
  - for each session it records the regime state at fixed checkpoints;
  - it records every trade the two CANDIDATE strategies would have taken, with zero capital: the plan, the simulated outcome and the 6-point checklist score;
  - it records every rejected candidate and why;
  - it records what the L0 guards *would* have done (risk-multiplier, halt flags).
- **It is not:**
  - an allocator (P3);
  - the LLM reviewer (P2);
  - a paper strategy in `paper_daily.sh`;
  - something any stage, model or the dashboard reads;
  - an order (PAPER ONLY).
- **Purpose:** to start the forward clock. The confirmatory answer needs 250–600 sessions.

## 3. Data (Upstox canon only)

| Input | Timeframe | Available from | Lands |
|---|---|---|---|
| Stock fills, intrabar stops | 1m NSE_EQ | 2026-07-20 | same evening, about 19:00 IST |
| Signals, ATR, BB, RSI | 15m | 2022-01-03 | about 16:40 IST |
| Daily context | 1d, sessions ≤ T−1 | 2019-09-03 | T−1 by about 08:32 on T |
| Indices | NIFTY 50, NIFTY BANK, INDIA VIX | same | same |
| Results | `results_event` (F4) | — | — |
| Corporate actions | `pit` CA views | — | — |
| Macro events | `backend/app/shadow/event_calendar.csv` (versioned, sha in the policy; entered ex-ante: RBI MPC decision day, Budget, FOMC decision night, the NIFTY **monthly** expiry = the last Tuesday, a holiday moving it to the previous trading day; weekly expiries are not events) | new | extended before each quarter (next: before 2027-01-01, with the Budget) |

- **PIT rule:** at checkpoint *c* of session *T*, a value may use only bars with `event_end ≤ c`, plus 1d bars of sessions ≤ T−1.
- **Prices:** `pit.bars_adjusted` at the run's cutoff.

## 4. Regime engine v0 (L1 + L2)

**Pre-session features** (data ≤ T−1):
- `nifty_adx14`, `bank_adx14` (Wilder);
- `nifty_vs_ema50`, `bank_vs_ema50` (sign);
- `breadth_50dma`: % of the universe with close > SMA50;
- `ad_ratio`;
- `nh_nl_20`;
- `vix_close`, `vix_pct252`, `vix_chg_1d`;
- `nifty_sigma20`: the σ of daily returns over 20 sessions;
- `nifty_ret_1d`;
- the event flags: the calendar, the share of universe names with results on T, a special session, and `holiday_thin` (the session before or after an exchange holiday, or 24–31 December).

**Open features** (09:15, from the first 1m bar):
- `nifty_gap` = open(T) / close(T−1) − 1, expressed in σ units (`nifty_gap / nifty_sigma20`).

**Intraday features** (09:30, 10:30, 12:00, 13:30):
- `nifty_from_open`;
- `breadth_above_open`;
- `breadth_above_vwap`;
- `ad_ratio_intraday`.

**State, first match wins:**

| Order | State | Rule | Risk multiplier (recorded; applied from P3) |
|---|---|---|---|
| 1 | `SHOCK` | `vix_pct252` ≥ 90, or `vix_chg_1d` ≥ +20 %, or \|`nifty_ret_1d`\| ≥ 2σ20, or `ad_ratio` ≤ 0.2 | 0 for new reversion entries; 0.25 otherwise |
| 2 | `EVENT_WAIT` | a calendar event on T (RBI / Budget / FOMC night / expiry), or ≥ 5 % of the universe reports results on T | 0.5 |
| 3 | `TREND_UP` | `nifty_adx14` ≥ 25, NIFTY and BANKNIFTY both > EMA50, and `breadth_50dma` > 60 % | 1.0 |
| 4 | `TREND_DOWN` | `nifty_adx14` ≥ 25, both < EMA50, and `breadth_50dma` < 40 % | 0.5 (reduce gross) |
| 5 | `RANGE` | `nifty_adx14` < 20 | 0.5 (smaller size) |
| 6 | `MIXED` | otherwise; indecision → stand aside | 0 |

**Modifiers:**
- `holiday_thin` multiplies the risk multiplier by 0.5.
- At 09:15, \|`nifty_gap`\| ≥ 2σ20 sets an intraday `SHOCK_OPEN` flag with the `SHOCK` multipliers for that session.

**Day-type tag** (at each checkpoint):
- `TREND_DAY_UP`: `nifty_from_open` ≥ +0.6 % and `breadth_above_open` ≥ 65 %;
- `TREND_DAY_DOWN`: the mirror image;
- `RANGE_DAY`: \|`nifty_from_open`\| < 0.3 %;
- else `UNCLEAR`.
- This tag is **PRAJNA DEFAULT** and is recorded only.

**What each snapshot stores:** the features, the rule fired, the multiplier, the input sha and the policy version.

## 5. Common construction and guards (L0 + L5)

**Universe:**
- the E4 eligible top-500 (liquidity, price ≥ ₹50, history, no suspect bars), restricted to security class STOCK (no ETFs or fund units) with a 20-session median turnover ≥ ₹5 cr;
- minus names with results intimated for T−1 or T, or a results outcome knowable in [T−1 09:15, T 09:15), all knowable before T 09:15;
- minus names with a non-dividend corporate action ex-dated inside the 15m history window (11 sessions), because intraday bars are raw and must not straddle an adjustment.
- These exclusions are counted on the run, not logged as skips.

**Book (per strategy):**
- reduced total equity = ₹10 L core (no locked-in profit in shadow);
- risk per trade 1 % = ₹10,000;
- qty = floor(₹10,000 / |entry − stop|) × the checklist size factor (1.0, or 0.5 when indicators do not confirm);
- notional ≤ ₹10 L per position (leverage ≤ 1:10 overall is never reached with ≤ 3 open at this size; recorded);
- quantity ≤ 1 % of the name's 20-session median daily volume.

**Caps:**
- at most 3 open positions, and a new entry only if open risk + new risk ≤ 3 %;
- ≤ 3 per sector;
- one trade per name per strategy per session.

**Halts, recorded per strategy book:**
- if realised + open P&L reaches −3 % in a session → `HALT_DAILY`: no further entries, and open trades keep their stops;
- the drawdown flags at 5 % and 10 % of the shadow book are recorded. In P1 they do not stop the recording; they are reported as "would have halved / halted".

**Checklist** (Playbook §4), recorded as six booleans; a trade requires ≥ 4:
1. pattern with its precondition;
2. stop at a structure level within 4 %;
3. volume ≥ 10-day average;
4. Dow agreement;
5. indicators confirm;
6. RRR ≥ 1.5.

Points 1, 3 and 6 are mandatory (the playbook calls points 1–3 near-mandatory; point 2 is satisfied by construction), and point 5 sets the size factor.

**Fills** (1m bars):
- **Entry:** the next 1m open after the signal bar ± (half-spread 5 bps + slippage).
- **Stop:** at the stop price, or at the bar's open on a gap-through (`STOP_GAP`).
- **Target:** at the target.
- **Same 1m bar touches both:** the stop first.
- **Time stop and EOD:** the 15:15 1m close.
- **Costs:** the dated `E4.MIS` tables; slippage at 0, 5, 10 and 20 bps.

## 6. The two shadow strategies, frozen specs v1

Both run on **every** session. The regime is a column, not a filter, so H3 can be tested.

### S1 `orb_breadth_v1`: range breakout with volume and Dow/breadth confirmation

**Range:** the 09:15–09:30 15m bar (high H, low L, width W = H − L).

**Long:** the first 15m bar ending 09:45–11:00 that meets all of these:
- its close is above H (point 1: a breakout from a range);
- its volume is ≥ the 10-session average volume of the same slot (point 3);
- the stock's 1d close at T−1 is above its 50-EMA, and NIFTY is above its open with `breadth_above_open` > 60 % at the bar's end (point 4: primary and market agree).

**Short:** the mirror image (close < L; below the 50-EMA; NIFTY below its open; breadth < 40 %).

**Stop:** the broken level H (for a long), widened to entry − 1 × ATR14(15m) if H is closer than 1 ATR.

**Target:** H + W (the range projected), the minimum target.
- RRR < 1.5 → `SKIP_RRR`.

**Point 5 (indicators):** ADX14(15m) ≥ 25 and RSI14(15m) between 50 and 80 for longs (20 and 50 for shorts) → full size, else half.

**Time stop:** 15:15.

**Ranking when caps bind:** checklist points, then the volume ratio.

### S2 `vwap_revert_v1`: Bollinger / VWAP range reversion in no-news names

**Long:** a 15m bar ending 10:00–14:00 that meets all of these:
- its close is ≤ the lower Bollinger band (20, 2σ) on 15m bars (point 1: a stretch inside a range);
- RSI14(15m) < 30;
- its close is below the session VWAP;
- \|the return from the T−1 close\| < 3 % (fade only noise);
- the stock's ADX14(1d) < 20 (the stock itself is ranging; point 4).

**Short:** the mirror image (≥ upper band; RSI > 70; above VWAP).

**Target:** the middle band (SMA20, 15m) at the signal bar, fixed.

**Stop:** entry ∓ 1 × ATR14(15m).
- RRR < 1.5 → `SKIP_RRR`.

**Point 3:** volume ≥ the 10-session slot average. A climactic stretch on low volume fails this point.

**Point 5:** RSI < 25 (> 75 for shorts) → full size, else half.

**Time stop:** 4 × 15m bars after entry (`TIME_NOT_WORKING`) or 15:15.

### Placebos
- **What they are:** for each strategy and session, the same entry times, sides, stop/target distances in ATR units, time stops and sizes, applied to names drawn at random (seed sha256(strategy, version, session)) from the eligible universe.
- **Purpose:** to separate the selection signal from the exit mechanics and the day's drift.

## 7. Hypotheses, metric and the looks (forward only)

**Hypotheses:**
- **H1:** S1 net R per trade > 0 in `TREND_UP` (longs) and `TREND_DOWN` (shorts), and > placebo.
- **H2:** S2 net R per trade > 0 in `RANGE`, and > placebo.
- **H3:** in-regime net R > out-of-regime net R for each strategy. This tests whether the regime engine adds value.
- **H4 (guards):** the recorded L0 multipliers (`SHOCK` and `EVENT_WAIT` reductions) would have improved the net R or the drawdown against flat sizing. This measures the regime engine as a risk tool.

**Primary metric:** net R per trade, averaged within the session and then over sessions. The CI is a session block bootstrap (10,000 draws, seeded).

**Secondary metrics:**
- expectancy;
- payoff ratio together with hit rate;
- net bps per session;
- max drawdown in R and its duration;
- the `SKIP_RRR` and checklist-fail shares;
- slippage sensitivity;
- trades per session.

**Window:** the forward sessions from the first session after the freeze. History is never evaluated for P&L.

**Looks:**
1. **At 60 forward sessions** (about late January 2027), with a 99.5 % CI.
   - Upper bound < 0 over all trades → RETIRED.
   - Lower bound > 0 in its regime and above placebo at 10 bps slippage → EXPLORATORY: minimum size in P3.
   - Otherwise → it continues.
2. **At 250 forward sessions**, with a 95 % CI and the same gates. ACCEPTED requires H1 or H2, plus H3 and beating placebo, at 10 bps.

**Rules for the window:**
- No other P&L look. Daily output is health only.
- No mid-window spec change. A change is a new `_v2` with its own fresh window.

**Honesty:** with ≤ 3 open trades and about 2–4 trades per session, 60 sessions give roughly 150–250 trades. That catches only large effects (≳ 0.15–0.2 R). The 250-session look is the real answer.

## 8. Schema: migration 0027 (additive; production backup + sha256 first)

All tables are append-only, have unique natural keys, and are idempotent on rerun.

**`shadow_policy`:** version, spec jsonb, `spec_sha256`, `code_git_sha`, `event_calendar_sha256`, `frozen_at`, status.

**`regime_snapshot`:** `market_date`, checkpoint (PRE / OPEN / 0930 / 1030 / 1200 / 1330), `policy_version`, `features` jsonb, `state`, `risk_mult`, `day_type`, `rule_fired`, `inputs_sha256`, `run_id`.

**`shadow_trade`:**
- identity: date, strategy, version, key, side, `is_placebo`;
- timing: signal / entry / exit timestamps;
- plan: entry, stop, target, qty, `size_factor`, `risk_inr`, `rrr`;
- checklist: `checklist` (6 booleans), `checklist_score`;
- outcome: exit, `exit_reason` (TARGET / STOP / STOP_GAP / TIME_NOT_WORKING / EOD);
- result: gross, costs jsonb, net, `net_r`;
- context: `regime_state`, `risk_mult`, `day_type`, `guard_flags` (`HALT_DAILY`, `DD_HALF`, `DD_HALT`), `evidence` jsonb, `run_id`.

**`shadow_skip`:** one row per rejected candidate (a name whose first signal bar was rejected; the name is then done for the session), with a closed reason list:
- `SKIP_RRR`, `CHECKLIST_LT4`, `CAP_OPEN_RISK`, `CAP_SECTOR`, `CAP_LIQUIDITY`, `HALT_DAILY`, `MOVE_GT_3PCT`, `NO_INTRADAY_BARS`, and from migration 0028 `VOL_TOO_HIGH`, `SR_BLOCKED`, `NO_SR_ZONE`, `HALT_FIRST_STOP`.

**`shadow_run`:** session, cutoff, policy shas, counts, `rows_sha256`, status (DONE, or SKIPPED with a reason for a non-normal session such as Muhurat).
- A refused session is **not** stored, and a later run retries it: the 1d or 1m bars of T are not stored yet; fewer than 90 % of the universe have ≥ 370 1m bars; the T−1 Nifty 1d bar is missing.
- Session T runs once its 1d bar is stored (the next morning), so the 21:30 job on T+1 records T.

The decision journal with plan adherence comes in P3, when a policy takes decisions.

## 9. Code, ops and tests

**Code:**
- `backend/app/shadow/`: `indicators.py`, `regime.py`, `strategies.py`, `fill.py` (reuses the `app.paper.sim` cost tables), `guards.py`, `store.py`, `job.py`.
- CLI `prajna shadow daily [--session D] --commit`. It catches up every session after the last DONE one.

**Ops:**
- runbook `ops/runbooks/shadow_daily.sh`;
- cron `30 21 * * 1-5`;
- its own `flock`;
- Telegram only on REFUSED or error, never P&L.

**Tests** (`prajna_test`):
- PIT (no bar after the checkpoint is read);
- indicator fixtures: ADX, EMA, RSI, ATR, BB, VWAP;
- the rule order and the multipliers;
- fills: stop-first, gap-through, time stops;
- RRR skip, checklist < 4, caps, daily halt;
- placebo seeds;
- idempotent rerun;
- the incomplete-1m refusal;
- the full suite `-m "not live"` green.

**Smoke before the freeze:** 3 historical sessions (2026-08-05, 2026-09-02, 2026-10-07), run `--no-commit --mechanics-only`.
- It reports counts, fill-inside-bar checks and the exit-reason mix.
- It computes **no P&L**.
- Bugs found there are fixed in the code; the numbers here do not change.

## 10. Freeze and execution order

1. The user accepts the four **PRAJNA DEFAULT** values in §1, or changes them now.
2. Build and tests; the suite is green.
3. Production backup to `/windows/prajna_archive`, sha256 verified; then `alembic upgrade` to 0027.
4. Write `config/event_calendar.csv` for November–December 2026: RBI MPC, FOMC and expiry dates from the official published schedules, entered by hand.
5. Smoke run (mechanics only).
6. **Freeze:** commit with `Status: FROZEN` and insert the `shadow_policy` rows. The forward start is the first session after the freeze.
7. Install the cron line, with the user's approval of that exact line.

**Left untouched:**
- the E5 forward test (look about 2026-12-18);
- the E6 monitor;
- `paper_daily.sh`;
- the Stage 1–3 code and gates;
- frontend/ and backend/app/api/.

## Amendment 2026-10-27: daily outcomes visible to the admin (Strategy Lab)

The user decided (2026-10-27): "hume har stratigy ka per day performance dikhana hai or saare performace history bhi save ho sabkuch database mai … baaki 60 day session 250 session to asitis chalte rahenge".

**From 2026-10-28, this test's daily outcomes are shown to the admin** on the Strategy Lab dashboard and in a nightly Telegram summary (docs/STRATEGY_LAB.md).

**Unchanged:** the frozen rules, the forward window, the data, the metrics, the gates and the look dates. The look does not read any lab table.

**Changed:**
- The look report must state that outcomes were visible daily from 2026-10-28.
- No rule may be changed because of the daily numbers. A change is a new version with its own fresh forward window.
- **Switches.** The admin may switch a variant off (`strategy_switch`). That session's run then records one `SWITCHED_OFF` skip row for the variant, with no trades and no placebo. The look reports every switched-off session as a protocol deviation. The spec and its sha are unchanged.
