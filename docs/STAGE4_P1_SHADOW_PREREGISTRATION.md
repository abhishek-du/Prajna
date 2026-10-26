# Stage 4 v2, phase P1: regime engine + shadow strategy library (pre-registration DRAFT)

**Status: DRAFT, awaiting user approval of the parameters below. Nothing is built, migrated or scheduled.**
Parent design: `docs/STAGE4_AI_AGENT_DESIGN.md` (L1, L2, L3, L5, L7). Doctrine: `docs/VARSITY_PLAYBOOK.md`.

Approved by the user on 2026-10-26: start P1. The first two CANDIDATE strategies are the recommended ones, breakout + breadth and VWAP range reversion. Approval of this document's exact numbers is still needed before the freeze (§9).

## 0. What P1 is, and what it is not

- **It is** a daily, after-the-close **shadow** run:
  - for each session it records the regime state at fixed checkpoints;
  - it records every trade the two CANDIDATE strategies *would* have taken (size computed but zero capital), plus every candidate it rejected and why;
  - everything goes to new append-only tables.
- **It is not:**
  - an allocator;
  - an LLM reviewer (that is P2);
  - a paper strategy in `paper_daily.sh`;
  - anything a stage, model or the dashboard reads;
  - an order of any kind (PAPER ONLY, no broker call).
- **Its job:** start the forward clock. The confirmatory answer needs 250–600 sessions (design §3), so every session not recorded is lost for good.

## 1. Data (Upstox canon only)

| Input | Table / timeframe | Available from | Lands |
|---|---|---|---|
| Stock 1m bars (fills, VWAP, stops) | `canon_market_bar` 1m, NSE_EQ (3576 keys) | 2026-07-20 | same evening, about 19:00 IST |
| Stock 15m bars (signals, ATR) | 15m | 2022-01-03 | same day, about 16:40 IST |
| Daily context (ATR, SMA, breadth) | 1d, sessions ≤ T−1 only | 2019-09-03 | T−1's bar by about 08:32 on T |
| Index | NIFTY 50, NIFTY BANK, INDIA VIX (NSE_INDEX) | as above | as above |
| Results days | `results_event` (F4) | — | — |
| Corporate actions | `pit` CA views | — | — |

- **Point-in-time rule:** a value used at checkpoint *c* of session *T* may only use bars whose `event_end ≤ c`, plus daily bars of sessions ≤ T−1.
- Prices are `pit.bars_adjusted` at the run's cutoff, exactly as in the paper job.
- **No new data source.** News-AI output is *not* used in P1, because its own validation is forward-only and separate.

## 2. Regime features v0 (L1): fixed definitions, no tuning

**Pre-session features**, computed from data ≤ T−1:
- `nifty_adx14`: Wilder ADX(14) on NIFTY 1d.
- `nifty_trend`: +1 if close > EMA20 > EMA50; −1 if close < EMA20 < EMA50; else 0.
- `vix_close` and `vix_pct252`: the percentile of the T−1 VIX close in its last 252 sessions.
- `breadth_50dma`: % of the eligible universe (§4) with close > SMA50.
- `ad_ratio`: advancers / (advancers + decliners) on T−1.
- `nh_nl_20`: (% at a 20-day high) − (% at a 20-day low).
- `nifty_ret_1d`: T−1 close-to-close return.
- `event_flags`:
  - the count of universe names with a results event on T;
  - a special session (from the trading calendar).

**Intraday features**, at checkpoints 09:30, 10:30, 12:00 and 13:30 IST:
- `nifty_from_open`: NIFTY return from the 09:15 open.
- `breadth_above_open`: % of the universe above its own open.
- `breadth_above_vwap`: % of the universe above its session VWAP.
- `nifty_range_atr`: the NIFTY high−low so far divided by its ATR14 (1d).

## 3. Regime classifier v0 (L2): a rule table, first match wins

The thresholds are the Varsity/standard textbook values. They are **not** fitted to any Prajna data.

| Order | State | Rule (pre-session) |
|---|---|---|
| 1 | `EVENT` | special session, or ≥ 5 % of the universe reports results on T |
| 2 | `HIGH_VOL` | `vix_pct252` ≥ 80, or \|`nifty_ret_1d`\| ≥ 2 % |
| 3 | `TREND_UP` | `nifty_adx14` ≥ 25, `nifty_trend` = +1, and `breadth_50dma` ≥ 55 % |
| 4 | `TREND_DOWN` | `nifty_adx14` ≥ 25, `nifty_trend` = −1, and `breadth_50dma` ≤ 45 % |
| 5 | `RANGE` | `nifty_adx14` < 20 |
| 6 | `MIXED` | everything else |

**Intraday day-type tag**, recorded at each checkpoint; it does not change the pre-session state:
- `TREND_DAY_UP`: `nifty_from_open` ≥ +0.6 % and `breadth_above_open` ≥ 65 %;
- `TREND_DAY_DOWN`: the mirror image;
- `RANGE_DAY`: \|`nifty_from_open`\| < 0.3 % and `nifty_range_atr` < 0.5;
- else `UNCLEAR`.

**Recording:** each snapshot stores the feature values, the rule that fired, the input sha and the policy version.

## 4. Common mechanics for both strategies (L5)

**Universe:**
- the E4 eligible universe (`app.training.e4.eligible`: liquidity and history filters, suspect names out) on T;
- minus names with a results event on T or T−1;
- minus names with a corporate-action ex-date on T.

**Book:**
- notional equity ₹10 L per strategy;
- risk per trade 0.5 % = ₹5,000;
- qty = floor(risk ₹ / |entry − stop|), capped at ₹2 L notional and at 1 % of the name's 20-session median 1m volume × 375;
- at most 5 trades per strategy per session, ranked by the strategy's ranking key;
- one trade per name per strategy per session;
- open risk at most 5 × 0.5 % = 2.5 % (≤ 3 %, playbook law 1).

**Stops, targets and RRR:**
- the stop is set at entry and never widened;
- the target is fixed;
- a candidate whose RRR is below 1.5 is **skipped** and logged as `SKIP_RRR`. The stop is never moved into noise.

**Fills, simulated on 1m bars:**
- **Entry:** the open of the 1m bar after the signal bar closes, ± (half-spread 5 bps + slippage).
- **Exits:**
  - **Stop:** if a 1m bar's low (high for shorts) crosses the stop, the fill is at the stop or at that bar's open if the bar opened through it (gap-through), less slippage.
  - **Target:** filled at the target.
  - **Same bar:** if one 1m bar touches both the stop and the target, the **stop fills first** (pessimistic).
- **Time stop:** the 15:15 1m close (MIS square-off).

**Costs:**
- the dated `E4.MIS` statutory and brokerage tables, as in `app.paper.sim`;
- slippage 0 bps for the primary result, with **5, 10 and 20 bps sensitivity** reported at the look (gap fade turned out to be slippage-fragile).

**Shorts:** MIS intraday shorts are allowed in simulation only.

## 5. The two shadow strategies (L3), frozen specs v1

**Run in all regimes:** both strategies run on **every** session, whatever the regime. The regime is a recorded column, so the conditional hypotheses in §6 can be tested.

### S1 `orb_breadth_v1`: opening-range breakout confirmed by volume and breadth
*Basis: Varsity M2 Dow theory (breakouts need volume; the averages must confirm); Innerworth's breadth confirmation.*

**Opening range (OR):** the high and low of the 09:15–09:30 15m bar.

**Long signal**, on the first 15m bar closing between 09:45 and 11:00 (bar end) that meets all of these:
- the bar's close is above the OR high;
- the bar's volume is ≥ 1.5 × that name's average volume for the same 15m slot over the last 10 sessions;
- `breadth_above_open` ≥ 60 % at the bar's end;
- NIFTY is above its open at the bar's end.

**Short signal:** the mirror image (close < OR low; breadth ≤ 40 %; NIFTY below its open).

**Stop:** the wider of
- the opposite side of the OR, and
- entry ∓ 1 × ATR14 on 15m bars (prior bars only, across sessions).

**Target:** entry ± 2 × |entry − stop|, which gives RRR 2.0.

**Time stop:** 15:15.

**Ranking key:** the volume ratio, descending.

### S2 `vwap_revert_v1`: intraday stretch back to VWAP, in no-news names
*Basis: Varsity M2 mean reversion with BB/RSI in ranges and VWAP (ch 20); Innerworth: fade noise, not information.*

**VWAP:** session VWAP from 1m bars, 09:15 onwards.

**Long signal**, on a 15m bar ending between 10:00 and 14:00 that meets all of these:
- the bar's close ≤ VWAP − 1.5 × ATR14 (15m);
- RSI14 (15m) < 30;
- \|the name's return from the T−1 close\| < 3 %. This is the news/information proxy: a larger move is treated as information and not faded.

**Short signal:** the mirror image (≥ VWAP + 1.5 × ATR; RSI > 70).

**Stop:** entry ∓ 1 × ATR14 (15m).

**Target:** the VWAP value at the signal bar's end, fixed at entry. The RRR is therefore about 1.5 or more; below 1.5 the candidate is skipped.

**Time stop:** the earlier of 8 × 15m bars after entry ("should work quickly") or 15:15.

**Ranking key:** the stretch |close − VWAP| / ATR, descending.

### Placebo (one per strategy)
- **What it is:** the same sessions, entry times, sides, stop/target distances, time stops and sizes as the real signals, but with a seeded random draw of names from that session's eligible universe.
- **Seed:** sha256(strategy, version, session).
- **What it isolates:** the value of the *selection* signal from the value of the exit mechanics and the market drift of the day.

## 6. Hypotheses, metric and the single look (forward only)

**Hypotheses:**
- **H1:** S1 net expectancy per trade > 0 in `TREND_UP`/`TREND_DOWN` pre-session states, and > its placebo.
- **H2:** S2 net expectancy per trade > 0 in `RANGE` states, and > its placebo.
- **H3 (regime value):** for each strategy, in-regime expectancy > out-of-regime expectancy. If H3 fails, the regime table adds nothing for that strategy.

**Primary metric:** net R per trade (the realised P&L ÷ the planned risk ₹), averaged within the session, then averaged over sessions. This metric is the session-clustered mean; the CI is a session block bootstrap, 10,000 draws, seeded.

**Secondary metrics:**
- net bps per session of the strategy book;
- hit rate together with the payoff ratio (never hit rate alone);
- max drawdown in R;
- `SKIP_RRR` share;
- slippage sensitivity at 5, 10 and 20 bps.

**Window:** the forward sessions from the first session after the freeze (§9). History before the freeze is never evaluated for P&L.

**Looks:**
1. **Harm / large-effect check at 60 forward sessions** (about late January 2027). It uses a 99.5 % CI.
   - Upper bound < 0 for a strategy over all its trades → that strategy is RETIRED.
   - Lower bound > 0 in its allowed regime, and above placebo → EXPLORATORY (it may then enter P3 with minimum size).
   - Otherwise it continues unchanged.
2. **Confirmatory look at 250 forward sessions.** It uses a 95 % CI, with the same gates. An ACCEPTED status requires H1 or H2 plus H3, and beating placebo, at 10 bps slippage.

**Rules for the window:**
- No other look at shadow P&L. The daily job prints counts and health only, and nothing reads P&L before a look.
- No spec change mid-window. A change is a new version (`_v2`) with its own forward window and no carried-over sessions.

**Sample-size honesty:**
- With about 3–5 trades per session per strategy, 60 sessions is about 200–300 trades. That detects only large effects, roughly 0.15 R per trade or more.
- The 250-session look is the real answer.

## 7. Schema: migration 0027 (additive; production backup + sha256 first)

All tables are append-only, have unique natural keys, and are idempotent on rerun.

**`shadow_policy`:**
- columns: `policy_version`, `spec` jsonb, `spec_sha256`, `code_git_sha`, `frozen_at`, `status`;
- one row each for the regime-v0 policy and S1, S2 and their placebos.

**`regime_snapshot`:**
- columns: `market_date`, `checkpoint` (PRE / 0930 / 1030 / 1200 / 1330), `policy_version`, `features` jsonb, `state`, `day_type`, `rule_fired`, `inputs_sha256`, `run_id`, `created_at`;
- unique on (date, checkpoint, version).

**`shadow_trade`:**
- identity: `market_date`, `strategy`, `version`, `instrument_key`, `side`;
- timing: `signal_at`, `entry_at`, `exit_at`;
- plan: `entry`, `stop`, `target`, `qty`, `risk_inr`, `rrr`;
- outcome: `exit`, `exit_reason` (TARGET / STOP / STOP_GAP / TIME / EOD);
- result: `gross_inr`, `cost_inr` jsonb, `net_inr`, `net_r`;
- context: `regime_state`, `day_type`, `evidence` jsonb (the feature values that triggered the trade), `is_placebo`, `run_id`;
- unique on (date, strategy, version, key, is_placebo).

**`shadow_skip`:** candidates rejected, with a closed reason list:
- `SKIP_RRR`, `CAP_TRADES`, `CAP_LIQUIDITY`, `NO_1M_BARS`, `RESULTS_DAY`, `CA_EX_DATE`, `MOVE_GT_3PCT`, `DUP_NAME`.

**`shadow_run`:**
- columns: the session, the cutoff, the policy shas, counts, `rows_sha256`, status (DONE / REFUSED with reason).
- Refusal cases:
  - the 1m bars for T are incomplete (fewer than 90 % of the eligible names have ≥ 370 bars) → REFUSED; a later run retries;
  - the 1d bar for T−1 is missing.

**The journal** (`decision_journal` with plan adherence) is deferred to P3. Shadow trades have no human or agent deviation to journal.

## 8. Code and ops

**Code:**
- `backend/app/shadow/`:
  - `regime.py`: features + rule table;
  - `strategies.py`: S1, S2, placebo;
  - `fill.py`: the 1m simulator, reusing the `app.paper.sim` cost tables;
  - `store.py`;
  - `job.py`.
- CLI `prajna shadow daily [--session D] --commit`. It catches up every session after the last DONE one, starting from the forward start date.

**Ops:**
- runbook `ops/runbooks/shadow_daily.sh`;
- cron `30 21 * * 1-5`, after the 1m bars land;
- `flock` on its own lock;
- Telegram on REFUSED or error only, never P&L.

**Tests** (on `prajna_test`):
- PIT: no bar with `event_end` > checkpoint is read;
- ADX, EMA, RSI, ATR and VWAP checked against hand-computed fixtures;
- the rule-table order;
- fills: gap-through stop, same-bar stop-first, time stop at 15:15;
- the RRR skip;
- caps;
- deterministic placebo seeds;
- idempotent reruns (0 inserted, same `rows_sha256`);
- refusal on incomplete 1m bars;
- the full suite `-m "not live"` stays green.

**Smoke run before the freeze:** 3 historical sessions (2026-08-05, 2026-09-02, 2026-10-07), run with `--no-commit --mechanics-only`.
- It prints counts, fill-inside-bar checks and the stop/target/time-exit distribution.
- It does **not** print or compute P&L.
- If mechanics bugs are found, the code is fixed. The parameters in this document are not changed.

## 9. Freeze and execution order

1. The user approves this document. Any number may be changed now, before the freeze, never after.
2. Build the code and tests; the suite is green.
3. Back up production to `/windows/prajna_archive` and verify the sha256; then `alembic upgrade` to 0027.
4. Smoke run (mechanics only).
5. **Freeze:** commit the code and this document with `Status: FROZEN`. Insert the `shadow_policy` rows with the spec sha and the git sha. The forward start date is the first trading session after the freeze commit.
6. Install the cron line, with the user's approval.
7. The daily health line goes to the existing ops log. The looks happen at 60 and at 250 forward sessions only.

**Left untouched:**
- the E5 forward test (look about 2026-12-18);
- the E6 paper monitor;
- `paper_daily.sh` and its strategies;
- the Stage 1–3 code and gates;
- frontend/ and backend/app/api/.

## 10. Decisions needed from the user

1. Approve the numbers above:
   - ADX 25/20, breadth 55/45, VIX percentile 80;
   - OR 15 minutes, volume ratio 1.5×, VWAP stretch 1.5 ATR, RSI 30/70;
   - risk 0.5 %/trade and 5 trades/day.
   Or name any changes **now**.
2. Approve migration 0027 on production (with the backup) and the 21:30 cron line, once the build and the smoke run pass.
