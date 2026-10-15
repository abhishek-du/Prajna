# Stages 7–8: paper execution and monitoring (design + step 1)

**Status:**
- APPROVED by the user 2026-10-15 ("start building the Stage 7–8 paper-trading infrastructure").
- The design decisions below were taken under the user's delegation of 2026-10-15.
- Step 1 is implemented: a pure simulator with tests.
- Steps 2–5 are not built.

**Hard rule: PAPER ONLY.**
- Nothing in this design places, modifies or cancels a real order.
- There is no code path from `app/paper/` to any Upstox order endpoint.
- Live trading needs the user's explicit written authorization and a separate design. It is not part of Stages 7–8.

## 1. Scope

| Stage | What | Does not depend on |
|---|---|---|
| **7 Paper execution** | Turns a day's **target list** (from any strategy: the E4 runner, a future model) into simulated MIS orders, fills, costs, positions and the end-of-day P&L | Which model wins |
| **8 Monitoring** | Daily P&L against benchmarks, alerts (Telegram), drift checks, a scheduled-retraining hook | Which model wins |

## 2. Decisions (taken 2026-10-15)

| # | Decision | Chosen | Why |
|---|---|---|---|
| P1 | Product | MIS intraday only: buy at the open, square off at the close, nothing held overnight | The strategy is intraday (user, 2026-10-15) |
| P2 | Fill model | Market order at the official open, filled at open × (1 + half-spread + slippage). Sell at close × (1 − half-spread − slippage) | Same convention as E4a, so paper P&L is comparable with the research numbers |
| P3 | No-fill rules | No fill when the day is locked (high == low: a circuit), or when there is no open or close. The order quantity is capped at 1% of the previous session's volume (participation cap); the remainder is "unfilled", never invented | Realistic and conservative |
| P4 | Quantity | floor(order value / fill price) shares; the leftover cash stays as cash | Real orders are whole shares |
| P5 | Costs | `app.training.e2.order_cost_parts` with the dated MIS rates (`e4.MIS`), per executed order, plus spread and slippage | One cost table for research and paper |
| P6 | Capital | ₹10 L, K = 10, ₹1 L per order (E4 D3) | As the research |
| P7 | Determinism | The simulator is a pure function of (targets, bars, config). Every run records its inputs' sha256 | Replayable and auditable |
| P8 | Storage (step 2) | New append-only tables `paper_run`, `paper_order`, `paper_fill`, `paper_day`. Migration plus a backup first | Same discipline as Stages 1–4 |
| P9 | Safety | The `app/paper` package may not import `app.vendor`, `httpx`, `requests` or `websockets`. A test enforces it. Every record carries `mode = 'PAPER'`, and a database CHECK allows only `'PAPER'` | The paper-only rule is enforced by code, not only by convention |

## 3. Steps

1. **Simulator core (`app/paper/sim.py`) + tests. DONE (this commit).** It has no database, no network and no scheduler.
2. **Storage:** migration for the P8 tables, a writer (insert-only, idempotent per (run, session)), and a CLI `prajna paper simulate --targets <file> --session <date>`.
3. **Daily paper job:** after the close, it takes the day's targets from the strategy runner and simulates them on the day's bars (once those are stored), and writes `paper_day`. Cron is added only with the user's install, as before.
4. **Stage 8 monitoring:**
   - daily P&L against benchmarks: the Nifty 50 open → close and the equal-weight universe (C0), cumulative curve and drawdown;
   - Telegram alerts: missing targets, no fills, drawdown beyond a limit, cost share above a limit;
   - drift: the live picks' gap/turnover distribution against the research TEST distribution (PSI), and realized costs against the model.
5. **Retraining hook:** a scheduled re-run of the strategy's calibration/validation on new data. It **never** changes a live configuration by itself; any change needs approval.

## 4. What step 1 proves (tests)

- The fill and exit prices, whole-share quantities, cash and the cost parts on a hand-computed example.
- Locked days, a missing open or close, and the participation cap: the order is not filled (or only partly filled), and the reason is recorded.
- P&L identity: end cash − start cash = Σ (sell value − buy value) − Σ costs.
- Determinism: the same inputs give the same result and the same sha.
- **Safety:** `app/paper` imports no vendor or network module, and `mode` is always `PAPER`.
