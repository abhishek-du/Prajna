# Research Desk: LLM-led investigation, auto-watchlist and live tracking

**Status:** built on 2026-10-27, at the user's request. PAPER ONLY: the desk makes research suggestions and never places an order.

**What the user asked for (2026-10-27):** "agentic infra structure … jisse hamara system sirf formulas par blind na ho … stock bhada to kyu bhada, gira to kyu gira … targets, stop loss from every aspect, every POV like a detective … every decision should be a mixture of rules and LLM and best practices … high score automatically watchlist mai add ho jaye, kharab wale hat jaye … manager live monitor karega intraday mai"

**User decisions:**
- **LLM authority:** the LLM has the final decision, and it may override the rules.
- **Scope:** every liquid stock (~500).
- **Intraday:** live target/stop tracking, Telegram alerts, and re-investigation at 11:00 and 13:30.

The LLM-authority decision is an amendment to CLAUDE.md doctrine 7 for the desk only.

## Pipeline (`backend/app/desk/`)

| Step | Module | What it does |
|---|---|---|
| 1. Dossier | `dossier.py` | Builds the evidence per stock, each item with an id. See the evidence list below |
| 2. Rule judge | `rules.py` (`dash-plan-v2`) | The v1 dashboard plan plus guards: CIRCUIT (within 1 % of a limit, so AVOID), EXTENDED (> 3 ATR above the 20-day average, so WATCH with a pullback entry), ILLIQUID (< ₹5 cr, so AVOID), NEWS_MOVE, RESULTS_TODAY, BAD_DATA. Reward/risk is net of costs, with 5/10/20 bps slippage |
| 3. Investigator | `investigate.py` | Nova Pro (`amazon.nova-pro-v1:0`, temperature 0, prompt `desk-prompt-v1`). Output: why it moved (driver + cited ids), six viewpoint scores (technical, catalyst, fundamental, market, execution, risk), score, decision (STRONG_BUY / BUY / WATCH / AVOID / SELL), horizon, entry zone, stop, T1/T2 with their basis, thesis, risks, invalidation, and where it disagrees with the rules |
| 4. Validator | `investigate.validate` | The schema; every cited id must exist; for BUY the levels must be ordered stop < entry ≤ entry < T1 ≤ T2, with the stop 0.3–5 ATR from the entry. One retry, then INVALID. Overrides of the rule judge are recorded as `conflicts` (for example `LLM_BUY_vs_RULE_CIRCUIT_UPPER`) |
| 5. Watchlist | `watchlist.py` | ADD on BUY/STRONG_BUY with score ≥ 70. REMOVE on score < 50, AVOID/SELL, stop, T2, invalidation, intraday expiry, or 5 sessions without a refresh. The log is `desk_watch_event` |
| 6. Live tracker | `track.py`, run by the dashboard's live loop | Every 30 s Upstox quote: ENTRY_TRIGGERED, T1, T2, STOP, INVALIDATED (stop before entry) and EXPIRED (intraday, 15:15). Each event is written once and sent to Telegram |

**Dossier evidence (step 1):**
- **Price facts (`px`):** returns, gap, volume ×20d, ATR, RSI, MACD, distance to the moving averages.
- **Levels (`lvl`):** 20/60/252-day levels and support/resistance zones.
- **Move attribution (`attr`):** market (β × Nifty), sector excess and stock-specific.
- **News:** linked news over 72 h with the AI enrichment and the hours before the close.
- **Events:** results (`res`) and corporate actions (`ca`) within ±10 days.
- **Fundamentals (`fund`),** with sanity flags such as an implausible sector P/E or a P/E mismatch.
- **Context (`ctx`):** the P1 regime engine, the calendar, FII/DII.
- **Execution (`exec`):** turnover, circuit limits, costs.

## Runs (`ops/runbooks/desk_run.sh`; cron Mon–Fri)

| Time | Mode | Stocks |
|---|---|---|
| 19:45 | EVENING | Top 500 by turnover (STOCK class, price ≥ ₹50) plus the watchlist. Day T's candle comes from the stored 1m bars |
| 08:40 | MORNING | Names with overnight news, results or corporate actions, plus the watchlist. The regime comes from the last evening run |
| 11:00, 13:30 | INTRADAY | The watchlist plus the 20 largest live movers, on live quotes |

**Cost and time:** about 6.5 s and ~2.5 k input tokens per stock on Nova Pro, with concurrency 2. An evening run takes about 30 minutes.

## Tables (migration 0031; append-only)

`desk_run`, `desk_dossier` (the packet and its sha), `desk_verdict`, `desk_watch_event` and `desk_track_event` (unique per verdict and kind).

## Forward record

Strategy Lab strategy `desk_llm_v1` (family DESK):
- each triggered suggestion is a paper trade at the triggering quote;
- the exit is the first of T1, the stop or the intraday expiry;
- MIS costs apply.

The Desk tab's Accuracy view counts triggers and outcomes by score bucket. These are the only test of whether the LLM's calls work. LLM signals are validated forward only, because pre-training leaks history.

## Dashboard

`#/desk` contains:
- **Watchlist & live:** status and distance to entry, stop and targets.
- **All verdicts:** filter by decision; rule overrides are shown in red.
- **Stock dossier:**
  - why it moved and the move split;
  - six viewpoints, and the LLM plan with its basis;
  - the rule judge with its conflicts and costs;
  - the news timeline with the citations starred;
  - tracking and history.
- **Watchlist log** and **Accuracy.**
