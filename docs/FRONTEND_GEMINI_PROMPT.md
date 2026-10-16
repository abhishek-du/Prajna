# Prompt for Gemini: Prajna frontend, next level

> Copy everything below this line into Gemini.

---

You are a senior full-stack engineer (React 19 + TypeScript + FastAPI + PostgreSQL). Your task is to take the **Prajna** web dashboard from a basic multi-tab viewer to a **professional, detailed control room** for an 8-stage NSE AI trading research system.

Work only in:
- `frontend/`;
- `backend/app/api/` (the dashboard's FastAPI read layer).

Read this whole brief before writing code.

## 0. Hard rules (non-negotiable)

1. **PAPER ONLY. No live trading.**
   - No button, endpoint, form or code path may place, modify or cancel a broker order.
   - Never call any Upstox order API.
   - "Portfolio / Execution" shows **simulated paper records only**, always labelled "PAPER — simulated fills, not a profitability claim".
2. **Read-only API.**
   - Every new endpoint is `GET`, plus the existing WebSocket.
   - Use the existing read-only DB session (`app/api/deps.py`), and set `SET TRANSACTION READ ONLY` for new queries.
   - No INSERT, UPDATE, DELETE or DDL, no job triggering, no shell commands from the API.
3. **No secrets in the browser.**
   - Never expose `.env` values, tokens, the DSN, Telegram credentials or Upstox credentials.
   - Do not log them. The browser talks only to `/api/v1/*`.
4. **Point-in-time honesty.**
   - Show data as it is: `null` is "—" with a reason, never 0 or interpolated.
   - Show `as_of`, `generated_at` and `knowable_at` where available, and never invent values.
   - Stage locks and statuses come from the backend, never hard-coded in the UI.
5. **Do not touch** anything outside `frontend/` and `backend/app/api/`:
   - other backend packages, migrations, cron, runbooks, `.env`;
   - the separate project `auto-trade-pro`.
   - If you need data that no table or file provides, say so in a TODO list. Do not change other modules.
6. Keep `npm run build` (tsc + vite) and `oxlint` clean. Add tests: Vitest + React Testing Library for components, and pytest for new API routes, using the test DB fixtures already in `backend/tests/` (the DB is always rolled back).

## 1. What exists today (verify by reading the code)

**Frontend (`frontend/`):**
- Stack: Vite 8, React 19, TypeScript 6, Tailwind 4, `lightweight-charts` 5, `lucide-react`. No router, no data-fetching library, no tests.
- `src/App.tsx`: a single page whose tabs live in `useState`; an IST clock; a WebSocket status indicator.
- `src/components/`, one view per tab, 92–569 lines each:
  - Overview, Explorer, CandleChart, Technicals, Fundamentals, GlobalMarkets, News;
  - Screener;
  - Signals and Portfolio (both "LOCKED" placeholders);
  - SystemHealth, AdminOps.
- `src/services/api.ts`: a fetch client for `/api/v1`, using the envelope `{data, meta}`.
- `src/services/websocket.ts`: connects to `/api/v1/ws/live`. Today that socket re-broadcasts stored bars; it is not a true tick feed.
- `src/types/api.ts`: response types.

**API (`backend/app/api/`, FastAPI, prefix `/api/v1`):**
- `overview`, `instruments` (list and `/{key}`), `candles/{key}?timeframe=1m|15m|1h|1d&adjusted&allow_low_confidence`, `technicals/{key}`, `fundamentals/{key}`, `global-markets`, `news`, `screener`;
- `signals` and `portfolio` (empty contracts);
- `health`, `ops/runs`, `ops/anomalies`, `ops/revisions`, `ops/backups`, `ops/warmup`, `ws/live`.
- A second read API, `backend/app/readapi/main.py`, already implements point-in-time endpoints you may **reuse as reference** (do not modify it): profile, quote, corporate actions, global candles, news articles / breaking / sources / latency / freshness / stats / stories.

**Database (PostgreSQL 18, Docker `prajna-postgres`, DB `prajna`). Use the canonical views, not raw tables, for market data:**
- **Market data:** `canon_market_bar` (only real sessions, positive prices; columns include `instrument_key`, `timeframe`, `market_date`, `bar_start_utc`, OHLCV, `knowable_at`, `fetched_at`, `price_basis`); `canon_excluded_bar` (excluded bars with a reason); `canon_coverage`; `canon_instrument` (`included`, `sector`, `lifecycle_status`).
- **Reference:** `instrument`, `trading_session`, `canon_corporate_action`, `canon_ca_factor`, `canon_fundamental`, `canon_global_bar`, `canon_macro_observation`, `canon_preopen`, `preopen_book`, `preopen_session_status`.
- **News:** `canon_news`, `news_item`, `news_story`, `news_entity_link`, `news_classification`, `news_assessment`.
- **Features (Stage 3):** `feature_value` (per session, snapshot PRE_SESSION / PRE_OPEN, feature id, value or a null reason), `stage3_event` (lock audit).
- **Research (Stage 4):** `training_dataset_run`, `training_label_run`, `training_sample`, `training_split`.
- **Paper (Stages 5–8):**
  - `paper_run`: strategy, `session_date`, `target_list` JSON with ranked targets and scores, `risk_limits` JSON, config, inputs sha;
  - `paper_order`, `paper_fill` (status FILLED/PARTIAL/NOT_FILLED, reason, qty, prices, charges JSON, P&L);
  - `paper_risk_decision` (APPROVED/REJECTED plus the rule's reason);
  - `paper_day` (daily cash, P&L, charges, turnover).
  - Strategies recorded today: `baseline_gap_fade`, `baseline_c0`, `bench_c0` (the benchmark).
- **Operations:** `ingest_run`, `ingest_anomaly`, `ingest_watermark`.

**Files the API may read (read-only, from `backend/var/`):**
- gate reports: `acceptance/stage1.json`, `stage2.json`, `stage3.json`;
- backfill: `logs/backfill/supervisor.log`, `logs/backfill/report_<date>.json`;
- runbook logs: `logs/daily/*.log`, `logs/paper/*`;
- E4 research results: `stage4/experiments/e4/*.json` and the docs in `docs/STAGE4_*.md`.

Parse these defensively. A missing file means "not available", not an error page.

## 2. The product: 8 stages, one control room

The system follows this pipeline. Every stage gets its own section with **status, evidence and drill-down**:

| Stage | Name | What the UI must show |
|---|---|---|
| 1 | Data ingestion | Coverage by timeframe (1d since 2020; 1h and 15m since 2022; 1m for the last 92 days), backfill progress per timeframe with ETA, last successful run per job, quarantined and excluded bars with reasons, corporate-action freshness, instrument-master changes (new listings, REMOVED_FROM_MASTER, ISIN changes such as splits) |
| 2 | Processing and storage | The Stage 2 gate (criteria A–P, PASS/FAIL, evidence), data-quality gates, the coverage-state matrix, point-in-time timestamps |
| 3 | Feature engineering | The Stage 3 gate (A–O); the feature registry (version, sha, count, groups: price/technical, volume, fundamental, event, news, market context, pre-open); per-snapshot completeness (values vs null reasons); per-instrument feature cards; the refusal audit (`stage3_event`) |
| 4 | Prediction research | The experiment ledger E1–E4: hypothesis, pre-registration, status (NOT RUN / CALIBRATING / INADEQUATE / LOOK TAKEN / ACCEPTED / REJECTED), calibration tables (Wilson intervals), results with CIs; a "no profitability claim" banner; never fabricate a model output |
| 5 | Signals / targets | The daily `TargetList` per strategy (ranked keys, score, `decision_at`, source), with diffs between days |
| 6 | Risk | The limits in force; every APPROVED/REJECTED decision and its rule (drawdown halt, daily-loss halt, min price, min turnover, sector cap, max positions); halt banners |
| 7 | Paper execution | Fills per day (status, reason, qty, buy/sell price, charges breakdown, P&L); fill rate; not-filled reasons (locked day, participation cap, insufficient cash) |
| 8 | Monitoring | The equity curve vs Nifty 50 open→close and `bench_c0`; drawdown curve; Sharpe, hit rate, cost share, fill rate; alerts; score drift (PSI); a forward-only toggle (from 2026-10-16) separating replayed days from forward days |

## 3. Pages and features (build all; each must be useful on its own)

**A. Global layout**
- Use React Router with real URLs, e.g. `/stocks/:key`, `/stages/4/e4`, `/paper/:strategy`. Deep links must work.
- Left sidebar grouped by stage (1–8) plus Market and Ops.
- Top bar:
  - IST clock;
  - market state (pre-open 09:00–09:15, open 09:15–15:30, closed, holiday), taken from `trading_session`, not hard-coded;
  - WebSocket state;
  - a global instrument search (⌘K command palette);
  - a "PAPER ONLY" badge that is always visible.
- Dark and light themes; dense, terminal-like tables; Indian number formatting (₹, lakh/crore, `en-IN`).
- Use TanStack Query (caching, retries, stale indicators) and TanStack Table (sort, filter, column chooser, CSV export, virtualisation for 3,500+ rows).
- Every widget shows `as_of` / last refresh and a "data stale" warning when older than its expected cadence.

**B. Home: Control room**
- One row of 8 stage cards (status, last change, a key number, alerts).
- Today's timeline of scheduled jobs (06:30 refresh, 06:45 CA, 07:00 morning, 08:25 pre-open, 09:00/09:22 Stage 3, 16:05 close, the backfill window, 15:40 paper job) with done / running / failed / missed state, derived from logs and `ingest_run`.
- An alerts feed (supervisor ALERT lines, gate FAILs, refusals).

**C. Market**
- **Stock page `/stocks/:key`:**
  - a candle chart (1m/15m/1h/1d, raw vs adjusted toggle, volume, corporate-action markers on ex-dates, excluded-bar markers);
  - quote and session stats;
  - fundamentals history and corporate actions;
  - news timeline with sentiment;
  - Stage 3 feature values for the latest snapshots;
  - pre-open IEP / imbalance history;
  - paper trades in this stock;
  - lifecycle and ISIN history.
- **Explorer / Screener:** filters (sector, security class, price, turnover, P/E, gap %, feature values), saved screens kept in localStorage.
- **Global markets and macro:** each series with its finality labels.
- **Pre-open monitor:** the latest session's IEP, gap vs previous close, buy/sell imbalance, top gappers.
- **News intelligence:** sources, latency and freshness, stories, entity links, breaking news, per-source health.

**D. Stage pages 1–8:** as in the table in section 2. Each has evidence tables you can expand to the raw JSON.

**E. Research (Stage 4)**
- An experiment ledger page and a detail page for each experiment.
- Calibration visualisation: bars with Wilson CIs against the 2.5% line, per world type and predictor.
- A disclosure section showing the docs' disclosures verbatim (for example, the paper-view of 49 TEST sessions).
- Read-only. **No "run test" buttons.**

**F. Paper trading (Stages 5–8)**
- Strategy list.
- Strategy page:
  - KPIs;
  - equity and drawdown charts vs benchmarks;
  - a daily table (targets → approved → filled → P&L);
  - the day drill-down: target list (with scores), risk decisions, fills with the charges breakdown (brokerage, STT, stamp, exchange, SEBI, GST);
  - alerts and PSI.
- Compare two strategies on the same axes.
- Mark replayed sessions and forward sessions clearly (forward = 2026-10-16 onwards).

**G. Ops**
- **Backfill:** progress bars per timeframe (covered / total), rate per hour, ETA, supervisor state (RUNNING / WAITING_LOCK / WAITING_CLOSE / WINDOW_CLOSED / PAUSED / DONE), disk free, recent BACKFILL_PROGRESS lines.
- Ingest runs with filters; anomalies; revisions; backups (size, sha, verified); a log viewer (tail of the whitelisted log files only, with secret redaction defensively applied).
- The Telegram log shows counts and times only, never message bodies containing tokens.

## 4. New read-only API endpoints you will need (in `backend/app/api/`)

Design them with the existing `Envelope[T]` and `Meta`, Pydantic schemas in `schemas.py`, pagination (`limit` ≤ 500 plus `offset`), and an indexed query plan. Suggested set:
- `GET /stages`: the status of all 8 stages (from the gate JSONs, `stage3_event`, the paper tables and the experiment files).
- `GET /stages/1/coverage`, `/stages/1/backfill` (parse the supervisor log and `ingest_run` progress), `/stages/2/gate`, `/stages/3/gate`, `/stages/3/registry`, `/stages/3/snapshots?date=`, `/features/{key}?snapshot=&date=`.
- `GET /research/experiments`, `/research/experiments/{id}` (from the files and docs).
- `GET /paper/strategies`, `/paper/{strategy}/days?from&to`, `/paper/{strategy}/days/{date}` (target list, risk decisions, fills), `/paper/{strategy}/summary?from&to&forward_only` (the same maths as `backend/app/paper/monitor.py`: reuse the functions by import, do not reimplement).
- `GET /preopen/{date}`, `/preopen/{key}/history`.
- `GET /ops/schedule/today`, `/ops/logs/{name}?tail=` (whitelist only, redact any `token|secret|password|key=` pattern), `/ops/supervisor`.

Write a pytest test for each endpoint. Add a guard test that the API router has **no** POST, PUT, PATCH or DELETE routes, and that no module imports a broker or order client.

## 5. Quality bar

- Code-split routes so the first load stays fast (lazy routes), and virtualise long tables. Charts must handle 100k bars (downsample on the server for long ranges).
- **Accessibility:** keyboard navigation, focus states, colour-blind-safe up/down colours with icons, not colour alone.
- **Every view handles three states:** loading skeleton, empty ("no data yet", with the reason from the API) and error (message plus retry).
- No mock or fake data in production builds. Fixtures belong only in tests.
- Keep the existing look recognisable, and refactor the large components (AdminOps at 569 lines, CandleChart at 426) into smaller pieces.

## 6. Delivery plan (one PR-sized step each; stop after each step and report)

1. Foundations: router, layout, TanStack Query/Table, theme, the command palette, the stage-status endpoint, the home control room.
2. Stages 1–3 pages, with the backfill and gate endpoints.
3. Stock page upgrade: chart markers, features, pre-open, paper trades.
4. Paper trading pages (Stages 5–8), with the paper endpoints.
5. Research ledger (Stage 4).
6. Ops log viewer, schedule timeline, polish, tests, performance pass.

**Report after every step:**
- files changed;
- new endpoints and their SQL;
- the test results (`npm run build`, `oxlint`, `vitest`, `pytest backend/tests -k api`);
- screenshots;
- anything you could not build because data is missing.

**Never claim that a feature works without having run it.**
