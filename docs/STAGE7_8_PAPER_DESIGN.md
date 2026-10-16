# Stages 7–8: paper execution and monitoring (design + step 1)

**Status:**
- APPROVED by the user 2026-10-15 ("start building the Stage 7–8 paper-trading infrastructure").
- The design decisions below were taken under the user's delegation of 2026-10-15.
- Step 1 is implemented: a pure simulator with tests.
- Step 2 is implemented (2026-10-16): migration 0022, `app/paper/store.py` and `prajna paper simulate`, with tests. Migration 0022 goes to production after a backup.
- Steps 3–4 and the generic part of Stage 6 are implemented (2026-10-16, scope approved by the user: "is scope ke saath shuru kar do"). They run by hand only; no cron line is installed.
- Step 5 (retraining) and the strategy-dependent risk (stops, targets, volatility sizing) are not built. They wait for a validated strategy and the exit design (E4b).

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
2. **Storage. DONE (2026-10-16).**
   - **Migration 0022:** `paper_run` (unique per strategy and session), `paper_order`, `paper_fill` and `paper_day`.
     - Each table has a CHECK that `mode = 'PAPER'`, and an append-only trigger.
     - `paper_order.product` must be `'MIS'`.
     - `paper_fill`: qty > 0 exactly when the order is filled.
   - **`app/paper/store.py`:**
     - It reads the session's canonical 1d bar (raw prices) and the volume of the previous trading session.
     - Writes need the write token.
     - The same inputs again return `ALREADY_PRESENT`; different inputs are refused, so a stored day is never overwritten.
   - **CLI:** `prajna paper simulate --session D --targets FILE --strategy NAME [--commit] [--fills]`. It runs as a dry run unless `--commit` is given, and refuses a dirty tree when committing.
   - **Tests:** `tests/paper/test_store.py`.
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


## 5. Pipeline built 2026-10-16 (steps 3–4, generic Stage 6)

**Flow:** strategy → `TargetList` → Stage 6 limits → simulator → `paper_*` tables → Stage 8 report.

| Part | Module | What it does |
|---|---|---|
| **Stage 5 → 7 contract** | `app/paper/targets.py` | `TargetList` (strategy, session, `decision_at`, ranked keys and scores, entry/exit rule, source, meta). It is validated before anything else: keys unique; ranks 1..n; the rule must be OPEN→CLOSE (the only one the simulator implements); **`decision_at` ≤ 09:15 IST of the session** (no look-ahead). Its canonical JSON and sha256 are kept on `paper_run.target_list`. |
| **Strategy adapters** | `app/paper/strategies.py` | `baseline_gap_fade` (E4 arm P) and `baseline_c0` (K random names from the same E4 universe, seeded by the date). Both use **the E4 rules themselves** (`e4.eligible`, `e4.gap_fade`), so a validated E4 predictor plugs in unchanged. These are **pipeline baselines with no claimed edge**. |
| **Stage 6, generic** | `app/paper/risk.py` | In order: drawdown halt (10% of capital), daily-loss halt (3%, next day only), min price ₹50, min median turnover ₹5 crore, at most 3 names per sector (an unknown sector counts as one sector), at most 10 positions. Every target gets an APPROVED/REJECTED row in `paper_risk_decision`, with the rule's name. |
| **Paper job** | `app/paper/job.py` | Runs session by session, in order. The risk state (drawdown, last day's P&L) comes from the strategy's earlier `paper_day` rows. A halted day is recorded with 0 targets. |
| **Stage 8** | `app/paper/monitor.py` | Per day: paper return, Nifty 50 open→close, and `bench_c0`: the C0 draw, never halted, as the fair benchmark (same universe, costs and fills). The halted `baseline_c0` stopped measuring after its 10% drawdown in the 2026-10-16 replay. Hit rate counts traded days only. A session counts as missing only after the strategy's first day and once its bars exist. Summary: cumulative return, max drawdown, Sharpe (252), hit rate, fill rate, cost share. Alerts: missing session, no fills, drawdown > 5%, cost share > 50%, score PSI > 0.25. Every report carries the PAPER-ONLY disclaimer. |
| **CLI** | | `prajna paper replay --strategy S --from A --to B [--commit]`; `prajna paper report --strategy S --from A --to B [--text]`. |
| **Telegram** | `ops/runbooks/paper_report.sh` | Sends the text report. Not scheduled. |

**When data is knowable:**
- The rules read close and volume of sessions before d, plus the official open of d (known at 09:15).
- Live, that open would come from the pre-open auction (IEP). In replay it is read from the stored 1d bar of d, which lands the next morning, so the job for d runs on d+1.
- The research-only mask that reads close(d) is not applied.
- Bars come from `pit.bars_adjusted` at one cutoff, as in the E4 dataset. The rules use only ratios, which a later split leaves unchanged.

**Not built:**
- stops, targets and volatility sizing (they wait for E4b);
- ML scoring;
- retraining and A/B testing;
- any real order path.
