# Strategy Lab: the admin dashboard for strategy performance and forensics

**Status:** built on 2026-10-27, at the user's request. Everything is PAPER or SHADOW: nothing here places, modifies or cancels an order.

**What the user asked for (2026-10-27):** "hume har stratigy ka per day performance dikhana hai or saare performace history bhi save ho sabkuch database mai … proper admin dashboard … konsi stratigy ne aaj konse liye with detailed forensic report … baaki 60 day session 250 session to asitis chalte rahenge na"

## Unblinding amendment (applies to P1, P2, E5 and E6)

The pre-registrations said there would be no profit/loss look before the scheduled ones, and that the daily output would be health only. **From 2026-10-28, every strategy's daily profit/loss is shown to the admin** on the dashboard and in a nightly Telegram summary. This is the user's decision.

**What stays the same:**
- the frozen rules (`p1-shadow-v1`, `p2-reviewer-v1`, the E5 model `4db89a70…`, `e6-rule-v1`);
- the forward windows and the data;
- the metrics and gates;
- the look dates:
  - P1/P2: 60 and 250 sessions;
  - E5: 40 sessions;
  - E6: one look, around April 2027.

The look scripts do not read any lab table.

**What changes:**
- Each look report must state "outcomes visible to the admin daily from 2026-10-28".
- **No rule may be changed because of the daily numbers.** A change becomes a new `_v2` version with its own fresh forward window, as each pre-registration already requires.
- Switching a frozen P1 variant off stops its record (see below). It is logged as a protocol deviation and reported at the look.

## What it does

| Part | Where | When |
|---|---|---|
| Per-day performance, trade and day forensics | `prajna lab daily`, `ops/runbooks/lab_daily.sh` | 15:55 (paper) and 22:45 (after P1 21:30 and P2 22:15), Mon–Fri |
| Morning brief | `prajna lab brief`, `ops/runbooks/lab_brief.sh` | 08:30 (after the daily bars) and 09:10 (adds the E5 picks), Mon–Fri |
| Strategy switches | `prajna lab switch NAME --on/--off --reason …`, or the dashboard | any time; needs the write token |
| Dashboard | `app/dashboard`, http://127.0.0.1:8600/#/lab | live |
| Telegram | `python -m app.lab.summary`, sent by `lab_daily.sh` at 22:45 | nightly |

### Strategies covered (`app/lab/registry.py`)

- **P1, shadow:**
  - `orb_breadth_core_v1` and `orb_breadth_strict_v1` (S1 breakout);
  - `vwap_revert_core_v1` and `vwap_revert_strict_v1` (S2 mean reversion).
  - Each has its random-stock placebo. Each variant can be switched.
- **Paper:**
  - `baseline_gap_fade` and `bench_c0` (both on);
  - `baseline_c0` (off by default, as it was before the lab). All three can be switched.
- **E5:** `e5_ensemble`, the frozen model's selected names, valued from open to close after MIS costs at ₹1 L per name. Monitor only, no switch.
- **E6:** `e6_results_drift`. PICK positions are marked to market each day until the close of the 20th session; CONTROL names are its comparison group. Monitor only, no switch.

### Tables (migration 0030; append-only)

| Table | Holds |
|---|---|
| `lab_run` | One row per build (`DAILY` or `BRIEF`) and session. Readers use the latest. A rebuild with the same inputs writes nothing |
| `strategy_day` | Per strategy and session: trades, wins/losses, gross, charges, net ₹, net R (P1), placebo, regime (pre-market and open), day type, equity, drawdown, outcome mix, best and worst name |
| `trade_forensic` | Per trade: plan (entry/stop/target/RRR/checklist/signal facts), fills, exit, MFE/MAE in % and R, target traded after the exit, Nifty during the trade, regime, AI verdict, news before the signal with its lag, news during the trade, and the outcome class with the rule that set it |
| `day_forensic` | Per strategy and session: what was planned (*kya socha*), what happened (*kya hua*) and why (*kyun*), in English and Hinglish. There is also one `_MARKET` row and one `_BRIEF` grade row |
| `daily_brief` | The morning brief as it was before the open |
| `strategy_switch` | The switch log. The latest row per strategy is its state |

`shadow_skip` gains the reason `SWITCHED_OFF`.

### Outcome classes (`app/lab/forensic.py`; the first rule that matches wins)

| Class | Rule |
|---|---|
| `TARGET_HIT` | The exit reason is TARGET |
| `GAP_THROUGH_STOP` | A bar opened beyond the stop |
| `NEWS_SHOCK` | Stopped (or closed at a loss) while a linked news item became knowable during the trade |
| `STOPPED_IN_NOISE` | Stopped, then the target traded later the same day |
| `MARKET_TURNED` / `MARKET_AGAINST` | Nifty moved ≥ 0.3 % against the trade between entry and exit |
| `GAVE_BACK` | Was up ≥ 1 R (or ≥ 1 % on open→close trades) before losing |
| `STOPPED` | Any other stop |
| `TIME_EXIT_WIN` / `TIME_EXIT_LOSS` | A time or end-of-day exit, by the sign of the net |
| `CLOSE_WIN` / `CLOSE_LOSS` | Open→close trades: paper and E5 |
| `OPEN_GAIN` / `OPEN_LOSS` | E6 positions still open |
| `NOT_FILLED` | The order could not be filled in the simulation |

### The day's reasons (`day_why`)

- **No trade:** the top rejection reasons, or "no signal".
- **Regime fit or misfit:** the realised day type against the tool. A trend tool fits `TREND_DAY_*` and a range tool fits `RANGE_DAY`.
- **Caution:** the morning regime was MIXED, SHOCK or EVENT_WAIT.
- **Result:** the trade count and net.
- **Main loss driver:** the most common losing class.
- **Placebo:** the strategy against its placebo.

### Morning brief (`app/lab/brief.py`)

The brief contains:
- **Regime:** the frozen P1 regime engine's pre-market call, from data up to the previous close.
- **Events:** the macro calendar, results today (those names are excluded), and corporate actions.
- **S1 watchlist:** F&O names in a daily trend, with ADX ≥ 25 and ATR ≤ 3 %.
- **S2 watchlist:** F&O names with ADX < 20 that sit within 1.5 % of a support or resistance zone.

Each watchlist entry gives the stock's present condition, why it qualifies, what would trigger it and what would invalidate it.

The brief also lists the E5 picks once they are made (09:06) and the high-impact news of the last 24 h. It is labeled "unvalidated research signals, not advice". The next night's lab build grades it: whether each name triggered, and whether it moved the suggested way from open to close.

### Regime analytics

The dashboard shows strategy × morning regime and strategy × day type for real filled trades:
- trade count, hit rate, average net and average R per cell;
- a seeded bootstrap 95 % CI.

Paper and E5 trades use the day's P1 regime. A cell with fewer than 30 trades is shown as "too few trades", so noise is not read as signal.

## Switches

- **Paper:** `paper_daily.sh` takes its strategy list from `prajna lab enabled --family PAPER`. The precedence is:
  1. `PRAJNA_PAPER_STRATEGIES`, if set;
  2. otherwise the switches;
  3. the old default when the DB is unreachable.

  NONE skips the job.
- **P1:** `prajna shadow daily` passes the switched-off variants to `compute()`, which records one `SWITCHED_OFF` skip row per session for that variant and no trades or placebo. The spec and its sha are unchanged.
- **Every change** needs the write token and a reason, and stays in `strategy_switch`. The dashboard asks for the token once per browser session and keeps it in sessionStorage.

## Phase 2 (not built; needs its own approval)

A live intraday scanner on the Upstox WebSocket feed for the ~213 F&O names. It would write signals to a `live_signal` table and show them on the dashboard during the session.

## Intraday Buy List (user 2026-10-27)

**Built:** the Buy List is part of the morning brief (`candidates.BUYLIST`, `app/lab/buylist.py`).

**Picks:** every liquid stock (the brief universe minus today's results and corporate actions) that the rule judge `dash-plan-v2` or the Research Desk's latest pre-open verdict calls BUY. At most 40, ranked by desk score, rule score and agreement.

**Levels (intraday, in daily ATRs from the 09:15 open):**
- stop: −0.5 ATR;
- T1: +0.75 ATR, which is 1.5 R;
- T2: +1 ATR, the typical day high.

Before the open the levels are shown from the previous close. The desk's swing plan stays on its dossier page.

**Dashboard tab `#/buylist`:**
- the picks, with live price, move from the open, open-to-high, and T1/stop touched today;
- the end-of-day grade and the score cards of recent days.

**Grading:** each pick is graded on its 1-minute path as an intraday trade:
- buy at the 09:15 open;
- exit at the first of the stop or T1 (the stop first when both touch in one bar), else at 15:15;
- about 0.28 % costs and spread.

The grade is the `_BUYLIST` row of `day_forensic`.

**Telegram:** both messages are AI-written in Hinglish with emojis (Nova Pro, facts only; any unknown stock name means the fixed template is sent instead):
- 09:10 morning list (`lab_brief.sh`);
- 16:50 "did it make money" report (`lab_eod.sh`), which first builds the day's lab after the 1m bars are stored.

**First check (dry, 2026-10-27, not recorded):** 37 picks; 25 profitable; T1 18, stop 5, 15:15 exit 14; +1.02 % average after costs. One day proves nothing.

