# Stage 4/5 E6: post-results drift, pre-registration (APPROVED AS A PAPER MONITOR 2026-10-23; FROZEN at `e6 freeze`)

**Status: approved as a PAPER MONITOR.** The user's decisions of 2026-10-23 were "E6 ke liye D1 b+c approve, baaki proposed theek hai":
- **D1 (b):** a two-season paper monitor; the gates are reported, not decisive.
- **D1 (c):** results features proposed for E5.1.
- **D2–D5:** as proposed.

The rule is in `app/e6/monitor.py` (`e6-rule-v1`). **FROZEN 2026-10-23 15:06:50 IST:** rule sha256 `12aa3ef55b4cbe089476c131d9cfd6c7edb01380ee226eeedd62073d6009fcf1`, code `d2e3124` (see `var/research/e6/freeze.json`). The first events counted are those disseminated after the freeze; the first record is Tue 2026-10-27 at 08:50, for events with day 0 = Fri 10-23 (after 15:06) and day 1 = Mon 10-26.

## 1. Question

After a quarterly results announcement, do the stocks with the strongest market-adjusted reaction (day 0 + day 1) keep outperforming over the next 20 sessions, long-only, from an entry that is actually tradable, after delivery (CNC) costs, on results seasons that were never looked at?

## 2. Where this comes from (EXPLORATORY, 2026-10-23)

- **Data.** The NSE results exports downloaded by the user (F4, commit `2eeb56f`; 129,844 filings 2014–2026), and canonical 1d VENDOR_ADJUSTED bars 2020-01..2026-10-21. Nothing on or after 2026-10-22 was used, because the E5 forward TEST window starts that day.
- **Study.** `ops/measure/e6_results_event_study.py` (inputs: CSV exports of the bars and events, written to a scratch directory).
  - The event is the earliest dissemination per (instrument, period), within 75 days of the period end.
  - Day 0 is the first close after the dissemination.
  - The abnormal return (AR) is the stock's return minus Nifty 50's.
  - A window with any daily |AR| > 35 % is dropped.
- **Close-to-close numbers** (day-1 close entry; liquid ≥ ₹1 cr/day; 27,482 events, 27 quarters). Quintiles of CAR[0,1] within each quarter, then CAR[2,20]:
  - Q1 +12 bps, Q3 +67 bps, Q5 +154 bps.
  - Q5 − Q1 +142 bps, t 4.0, 23/27 quarters positive.
  - The spread is positive in every year from 2020 to 2026.
- **Risk on results days.** The median |AR0| is 2.56 %, about 2× a normal day. |AR0| exceeds 5 % on 22 % of events. The mean AR0 is −46 bps.
- **With the candidate rule of §3** (entry at the day-2 open, 20 sessions, a fixed threshold, ₹5 cr/day turnover, price ≥ ₹50, 35 bps round-trip cost), development 2020–2025:

  | Metric | Value |
  |---|---|
  | Picks | 2,739 |
  | Q5 net excess vs Nifty | +84 bps |
  | Q3 control | +39 bps |
  | Q5 − Q3 | **+81 bps** |
  | Weekly t | **1.34** (151 weeks) |

  Most of the close-to-close spread is lost to the day-2 gap and to clustering. The edge is much weaker than the close-to-close table suggests.
- **Known biases.**
  - **Survivorship:** only names listed today are in the data, so every quintile looks positive and only differences are meaningful.
  - **Late timestamps:** the Financial Results file carries the XBRL dissemination time, which is sometimes hours or a day after the results (TCS Q4 FY23: results 12 Apr evening, XBRL 13 Apr 12:50). This means no look-ahead, but day 0 may be one session late.
- **Disclosure.** While drafting, the 2026-01..2026-08 subset was also computed (Q5 − Q3 +120 bps, weekly t 2.2, 19 weeks). That period is therefore **looked at** and cannot serve as a clean historical test. This is one more reason the test must be forward.

## 3. Rule (fixed at the freeze; candidate values from development 2020–2025)

| Item | Rule |
|---|---|
| Event | an NSE results filing (Outcome of Board Meeting / Integrated Filing – Financial / Financial Results), from the production announcements pipeline (`results_event` OUTCOME, exchange timestamp), within 75 days of the period end; the first filing per (instrument, period) |
| Day 0 | the first session whose close is after the dissemination (before 15:30 IST → that day; after → the next session) |
| Signal | CAR[0,1] = (stock − Nifty 50) close-to-close return over day 0 and day 1, from canonical daily bars (available by the 08:32 morning job) |
| Pick | CAR[0,1] ≥ **T5 = +3.27 %** (the 80th percentile of the development distribution, frozen as a number) |
| Control | the same season's events with CAR[0,1] in **[−1.85 %, +0.29 %]** (the development 40th–60th percentiles), traded identically, untraded in fact |
| Universe filters | previous close ≥ ₹50; median traded value of the 20 sessions before day 0 ≥ ₹5 cr; an NSE_EQ instrument ACTIVE in the master |
| Entry | **the open of day 2** (the first open after the signal is computable) |
| Exit | the close of the 20th session from the entry (day 21); no stop, no target (a stop / target is a separate, later rule) |
| Size | equal notional (₹1 lakh per pick, paper); overlapping positions allowed; no cap on the count (it is a measurement of the rule, not a portfolio) |
| Costs | 35 bps per round trip (STT 0.1 % per side, stamp, exchange and DP charges, GST, 5 bps half-spread per side); stress test at 1.5× |

## 4. Primary metric and inference

- **d_w** = for each entry week w: the mean net excess return (vs Nifty 50, open→close of the holding window) of the picks, minus the mean of the controls. A week without both picks and controls is not counted.
- **Inference:** the sign-flip randomization CI of mean d_w at level 0.975. Weeks are the unit, because events in a week share factor exposure.
- **Minimum detectable effect, stated in advance.** The development weekly sd of d_w is about 480 bps.

  | Forward weeks with picks | SE | MDE (80 % power) |
  |---|---|---|
  | 10 (one season) | ~150 bps | ~420 bps |
  | 20 (two seasons, ≈ Oct 2026 + Jan–Feb 2027) | ~107 bps | ~300 bps |
  | 40 (four seasons, ≈ one year) | ~76 bps | ~210 bps |

  The development effect is about 80 bps. **A forward test of this design will very likely read NOT_ACCEPTED even if the effect is real.** This is the main decision in §9.

## 5. Acceptance (all four; at the single look)

| Gate | Rule |
|---|---|
| B1 | the CI of mean d_w lies above 0 |
| B2 | mean d_w ≥ 0 with costs at 1.5× (52.5 bps) |
| B3 | mean net excess of the picks alone > 0 (not only relative to the controls) |
| B4 | mean d_w > 0 in each half of the forward weeks |

- ACCEPTED means the rule may become a Stage 5 paper strategy (or an E5.1 feature).
- NOT_ACCEPTED means it is reported as it is, and the rule is not used.
- **Secondary metrics** (never decisive): hit rate, the distribution of net returns, drawdown of the equal-weight book, results by turnover tercile and by sector, and CAR[2,10] and CAR[2,40].

## 6. Forward window and the single look

- The window starts with the first event disseminated after the freeze (`e6 freeze`) and runs for **N seasons (§9)**.
- Picks and controls are written when the signal is computable (after the day-1 bar is stored), before the day-2 open. A database CHECK enforces `recorded_at < entry_open_at`.
- There is one look, after the last pick's exit. No interim look: the status shows counts only.
- E6 and E5 run side by side and are independent. A stock may be both an E5 pick and an E6 pick; neither test reads the other.

## 7. Operations (built 2026-10-23)

- **Storage: files, not a migration.** For a non-decisive monitor, append-only files under `var/research/e6/` replace the proposed table. This avoids a 150 GB production backup and migration.
  - `freeze.json` holds the rule, its sha256 and the code's git sha. A changed rule is refused.
  - `signals/<entry day>.jsonl` is written once and never rewritten.
  - `look.json` is the ledger of the single look.
- **The CHECK becomes code.**
  - `prajna e6 record` refuses at or after 09:15 IST on the entry day (TOO_LATE) and refuses an existing file.
  - It reads only daily bars with `knowable_at <= now()`.
- **Commands:** `prajna e6 freeze --commit` (refuses a dirty tree), `e6 record [--commit]`, `e6 status` (counts only) and `e6 look` (refused before the window has closed and every row has exited; refused a second time).
- **Daily job:** `ops/runbooks/e6_daily.sh`, cron 08:50 Mon–Fri (after the 08:32 morning job stores the day-1 bars). Telegram gets counts only.
- **Tests:** `tests/unit/test_e6_monitor.py` covers the day-0 cut at 15:30, the classes and their boundaries, CAR[0,1], costs, the weekly look and its gates, the sign-flip CI on noise, and refusal of an unfrozen or changed rule.
- **Dry run on 2026-10-21..23** (read-only, with a pretend freeze date): 25–31 events per morning, of which 1–5 were PICK, 2–5 CONTROL, and 10–12 EXCLUDED (turnover or price). 2026-10-20 (Dussehra) was skipped correctly by `trading_session`.
- **Known limits, reported in the status and not filled:**
  - **Coverage of the live OUTCOME pipeline:** for 2026-10-01..22 it found 206 companies against 277 in the NSE CSV, about 75 %. A missed filing is a missed event.
  - **Calendar:** `trading_session` currently ends on 2026-12-31. The Jan–Feb 2027 season needs the 2027 calendar loaded before then; `e6 status` shows `calendar_ends`.

## 8. Not part of E6

- No stops or targets, no short side (cash shorts are not possible overnight), no position sizing beyond equal notional, no intraday entry.
- The NSE Closing Auction Session would allow entry at the day-1 close (closer to the close-to-close study). It needs a signal computed before the auction from intraday bars. That would be **E6b**, a separate pre-registration.

## 9. Decisions for the user

| # | Decision | Options | Proposed |
|---|---|---|---|
| D1 | What to do about the power problem (§4) | (a) forward 4 seasons (≈ 1 year) and accept a likely NOT_ACCEPTED; (b) forward 2 seasons as a **paper monitor** with the gates reported but not decisive, then decide; (c) do not run E6 as a strategy: add "days to results" and "results reaction" as features in E5.1 instead | **(b) + (c)**: the monitor costs nothing and the features use the same data |
| D2 | Turnover filter | ₹1 cr or ₹5 cr per day | ₹5 cr (Stage 6 `min_turnover_inr`) |
| D3 | Holding period | 10 or 20 sessions | 20 (fixed now; 10 reported as secondary) |
| D4 | Cost assumption | 35 bps per round trip | 35 bps; the user may confirm the Upstox delivery charges |
| D5 | Window start | first event after the freeze | as soon as the build is tested (Q2 FY27 season is running until about mid-November) |

**Decided 2026-10-23:** D1 (b)+(c); D2 ₹5 cr; D3 20 sessions; D4 35 bps; D5 start now.

After the decisions: build §7, run the tests, then freeze. The threshold numbers, the cost and the rule hash are written into this file and into `e6_freeze`, and the file becomes **FROZEN**.
