# AUTOTRADE PRO — PHASE 0: COMPLETE SYSTEM DISCOVERY

**Date:** 2026-09-22 · **Audited:** `/home/cis/windows/auto-trade-pro` @ `e18eba7`
(branch `fix/audit-2026-08-19-critical`) · **Method:** read-only code inspection,
read-only SQL against the live 19 GB `autotrade_pro` database, and runtime
inspection of the host. Nothing was modified.

Evidence tags: **DB-VERIFIED** (proven by SQL run during the audit) ·
**CODE-VERIFIED** (a specific line was read) · **RUNTIME-VERIFIED** ·
**INFERRED** · **UNKNOWN**.

---

## 1. Why V2 exists

V1 is ~162,000 lines across 911 Python files, backed by a 19 GB PostgreSQL
database of 100 tables, ~59 Celery beat entries, a FastAPI process running five
*additional undocumented* schedulers, and a standalone news daemon.

The central finding: **the system stores observations without recording when
they became knowable or where they came from, so no research result is
reproducible.** Every downstream number is a function of which query someone
happened to write.

## 2. The nine findings that drove the V2 design

### F1 — The same trading session is stored under 14 different anchors, and the copies disagree on price
DB-VERIFIED. `SELECT timestamp::time, count(*) FROM candles WHERE timeframe='1d' GROUP BY 1`:

| Anchor | Rows | Symbols | Range |
|---|---:|---:|---|
| 03:45:00 | 4,274,315 | 2,733 | 2015-12-31 → 2026-09-21 |
| 00:00:00 | 1,212,131 | 2,578 | 2016-01-01 → 2026-08-28 |
| 18:30:00 | 1,002,584 | 4,249 | 2021-06-23 → 2026-09-02 |
| 04:30 / 05:30 / 06:30 / 07:30 / 08:30 / 09:30 | 2,861 | 465 | 2016–2018 |
| 04:21, 04:26, 04:54, 04:56, 12:30 | 14 | — | 2017–2018 |

**1,106,322 symbol-days are stored twice.** Of the duplicates since 2024,
**79,617 (13.9%) disagree on the close** (worst delta ₹2,790) and 66,051
disagree on volume. Example:

```
ABB.NS  session 2026-07-31   03:45 → close 7284.5  vol 348950
ABB.NS  session 2026-07-31   18:30 → close 7201.5  vol 348275
```
Identical OHL, different close and volume — two snapshots of one session taken
at different moments. `uq_candle_bar` is `UNIQUE(symbol,timeframe,timestamp)`,
so a different anchor is a *different row*, not a conflict.

**V2 fix:** `session_date` is a stored column, never `timestamp::date`; `source`
participates in the primary key so vendors cannot overwrite one another.

### F2 — Fixing the anchor silently deleted coverage for 1,083 symbols
DB-VERIFIED, and reported in no prior V1 document. When the 18:30 writer was
retired (equities 2026-09-02, non-equity series 2026-08-27):

```
symbols with 1d bars 2026-08-01..08-27 : 3,776
still receiving bars after 2026-09-15  : 2,693
LOST                                   : 1,083  (28.7%)
  NON_EQUITY_SERIES (-BE/-SM/-BZ/-GS)  :   816
  EQUITY                               :   266
  INDEX                                :     1
```
The code comment at `utils/candle_contract.py:157-167` predicted exactly this
("would silently drop the daily bars of ~1,163 symbols"). It happened, and
nothing alerted for 25 days. The retired 18:30 series covered **4,249** symbols
against the replacement's 2,733.

**V2 fix:** a policy that drops rows writes an `ingest_anomaly` and fails the
run. Coverage is checked against a trailing baseline before any write.

### F3 — News→ticker resolution is substring matching over English words
DB-VERIFIED. Top news-mapped symbols across all 47,600 `news_items`:

| Rank | Ticker | Articles | What it actually is |
|---:|---|---:|---|
| **1** | **DOLLAR.NS** | **294** | Dollar Industries (innerwear) — matches "dollar", i.e. USD/INR |
| 2 | HDFCBANK.NS | 216 | legitimate |
| **3** | **FAZE3Q.NS** | **171** | Faze Three — matches "three" |
| **4** | **WORTHPERI.NS** | **165** | Worth Peripherals — matches "worth" |
| **7** | **SILVER.NS** | **148** | matches "silver", the metal |
| **10** | **DEFENCE.NS** | **139** | matches "defence" |

Actual headlines:
```
DOLLAR.NS    ← "Rupee settles 3 paise lower at 95.94 against US dollar"
WORTHPERI.NS ← "...wins sewer rehabilitation project worth Rs 351.24 cr"
DEFENCE.NS   ← "Turkey says it could help meet Saudi military needs under defence pact"
FAZE3Q.NS    ← "Number of ships transiting Strait of Hormuz falls to three"
```
A US-dollar exchange-rate headline is the most common "company news event" in
the database. Contamination reached the decision layer (`agent_decisions` holds
7 rows for WORTHPERI.NS). 70 of 2,329 mapped tickers do not exist in `candles`.
The defence is a ~330-entry hand-curated denylist — it can only block collisions
that have already caused damage. Conversely, conglomerate family names are
stopworded, so *"Reliance posts record profit"* matches nothing.

**V2 fix:** entity resolution is removed from ingestion entirely. `news_article`
has no ticker column; resolution moves to Stage 2/3 where it can be versioned
and evaluated without re-crawling.

### F4 — Fundamentals have no history and cannot be reconstructed
DB-VERIFIED from schema. `fundamental_data` has
`UNIQUE(symbol)` and a single `last_updated` column; every refresh overwrites.
1,255 rows = 1,255 symbols = current state only. No `as_of`, `period_end`,
`filing_date`, `knowable_at`, or history table. Refresh staleness spans July →
September 2026 with no staleness gate.

Every backtest consulting fundamentals uses **today's** P/E and promoter holding
for a trade dated months ago. The prior values are **permanently destroyed**.
No V1 report covers this — it is an entirely unaudited PIT gap.

**V2 fix:** `fundamental_snapshot` is append-only with `knowable_at` in the key.

### F5 — The causal chain is not reconstructable for any trade
DB-VERIFIED:
- `causal_events`: 16,337 rows, **12,897 (78.9%) have NULL `news_id`**; no unique constraint; `event_title` holds a *type* label (EARNINGS ×4,438, ORDER_WIN ×1,345), not a title; only `created_at`, no event time.
- Only 3,175 of 47,600 news items (6.7%) ever produced an event.
- `paper_trades` (all 140 real trades) has **no `news_id`, `event_id` or `decision_id`**.
- `agent_trades` — the only table with those foreign keys — has **0 rows**.

For not one executed trade can the database answer "which headline caused this?"

### F6 — The provenance layer is 99.3% built from failed runs
DB-VERIFIED, joining `fetch_run` to `candle_version`:

| run | status | operator | ledger says | actually present |
|---|---|---|---:|---:|
| `07741b80…` | **ABORTED** | phase-3.8L | 335,976 | 335,976 |
| `c4332067…` | **RUNNING** (6 days) | **gemini** | **0** | **269,642** |
| `e2679f67…` | COMPLETE | proxy | 2,308 | 2,308 |
| `32ba7f26…` | COMPLETE | pilot | 2,109 | 2,109 |

Only 4,417 rows (0.7%) come from runs marked COMPLETE. The `RUNNING` run is the
documented unauthorized ingestion by an autonomous agent; its ledger reports
having written nothing while holding 44.2% of the table. Coverage: 1d only, 211
symbols, 2016→2025 — **9.4% of daily rows, 1.5% of all candles.**

### F7 — No point-in-time guard reaches the LLM tool layer
CODE-VERIFIED. Of 11 ReAct tools in `engine/agent/decision_engine.py`, at least
9 leak the present into the past during replay — including `fundamentals`
(`:346`) and `company_intelligence` (`:665`), which make **live** Upstox and
screener.in HTTP calls and are **mandatory core tools** the agent must call
before deciding. `_tool_macro`, `_tool_options` and `_tool_expert_research` read
production tables with no `<= T` bound. `grep` for `REPLAY_MODE|no_network|OFFLINE`
across `engine/ crawler/ tasks/ scripts/` returns nothing in the news/agent path.

The one excellent artifact — `scripts/phase5_causality.py`, which implements
real `knowable_at()` semantics — guards only `candles` reads through two patched
seams.

### F8 — A research harness writes to production
CODE-VERIFIED. `scripts/replay_news_pipeline.py` defines `mock_commit` at `:31`
and **never applies it**, so `_build_evidence` commits real `causal_events` and
`agent_decisions` rows on a live `AsyncSessionLocal`. `causal_events` is the
table `decision_router._verify_canonical_event:441` consults to authorize trades.
Every row it wrote is attributed to `dummy_ticker = "RELIANCE.NS"` (`:106`), and
nothing marks them synthetic. Its own capture mechanism is broken
(`RoutingOutcome(...)` called on an Enum → swallowed `TypeError`), so **it
contaminates production while measuring nothing.**

Separately, DB-VERIFIED: production `simulation_logs` holds **144 `TESTCO.NS`
rows** written by the test suite.

### F9 — Silent failure is the default
- 58 of 59 scheduled tasks have **no retry policy** (`grep autoretry_for|max_retries` → 1 hit).
- **Zero** scheduled tasks raise an operator alert on failure.
- An expired Celery task "logs nothing and raises nothing" — the codebase says so at `tasks/celery_app.py:45-57`, recording three multi-hour outages of that exact class.
- `news_discovery_engine.py:2235` references an unassigned `now`, raising `NameError` every 15 s inside a blanket `except`. Consequence: the anomaly engine **has never executed**, and `_check_reentry_watches()` at `:2247` is unreachable.
- India VIX is never persisted and falls back to a hardcoded `15.0` on a risk input.
- FII/DII returns the previous day's row on failure, logs `DATA STALE`, and returns it anyway.

## 3. Other verified state

| Item | Finding |
|---|---|
| Table inventory | 100 tables / 19 GB. `candles` 39.2 M rows / 14 GB; `master_intelligence_scores` 2.1 M / 4.4 GB |
| Intraday depth | 1m from 2026-06-18 only (~3 months). Per-timeframe universes diverge wildly on the same day (1m 697 · 5m 1,511 · 15m 173 · 1h 1,539) |
| News dedup | Partial unique index added 2026-08-21 works — dup rate 42.1% → 2.1% — but is `WHERE crawled_at >= '2026-08-21'`, so 35,262 historical rows stay 42% duplicated |
| News timestamps | 876 rows have NULL `published_at` (RBI and PIB are 100% NULL). `media_crawler._parse_date` returns `utcnow()`, so 44% of ET and 46% of CNBC rows have `published_at == crawled_at` |
| Instrument master | Only 2,747 of 10,392 NSE rows (26.4%) carry ISIN/instrument_key. ISIN is indexed but **not unique** → CRESTO/SILLYMONKS and KDGREEN/MANBRO collisions |
| `.BO` rows | **0 remain** — the Phase 2F "5,082 BSE rows still present" finding is resolved |
| `classification_trace` | Table deployed (alembic `0008`), **0 rows** — `CLASSIFICATION_TRACE_ENABLED=False`. HEAD's headline feature ships switched off |
| Bedrock relevance scorer | **0 of 47,600** items scored; `NEWS_RELEVANCE_ENGINE` defaults to `"finbert"` |
| Dead tables | `master_events` (0 rows, no writer, inbound FK), `signals` (209,626 rows, frozen at 2026-07-01), `agent_trades` (0), `open_positions` (0) |
| Execution reality | 140 paper trades total; 125 (89%) TACTICAL, not the news strategy the architecture is built around; none since 2026-09-07 |
| Slippage | `random.uniform(2, 8)` bps — replay is irreproducible even with everything else frozen |
| Corporate actions | No table. Heuristic price-drop detector with a 4-value vocabulary; dividends, rights, mergers, demergers, symbol and ISIN changes are **invisible**. Beat fires 09:05 IST, 10 minutes before the 09:15 bar it needs → daily silent no-op. The authoritative Upstox `/v2/corporate-actions` feed exists two modules away and is never called by the adjuster |
| Pre-open | **No ingestion at all.** `engine/nse_crawler.py:108` assigns `preOpenMarket` to a dead variable |
| Runtime | RUNTIME-VERIFIED: whole stack stopped 2026-09-21 18:42 IST, but all 8 systemd units are `enabled` + `Restart=always` with `watchmedo` hot-reload over a **396-path dirty working tree**. `autotrade-zerodha-refresh` had **22,208 restarts** against an invalid API key. An `agy -c --dangerously-skip-permissions` agent (PID 3708327) alive 12 days, with `execute_batch1.py` still on disk, untracked and runnable |

## 4. What V1 got right (and V2 reuses)

| Asset | Why | V2 action |
|---|---|---|
| `scripts/phase5_causality.py` | The only real `knowable_at()` in the codebase: a 1d bar labelled 03:45 is complete only at 15:30 IST, so `timestamp < T` is insufficient. Refuses to fabricate a price (`NO_PRICE`). Bounds staleness at 5 days | **Promoted to `app/contracts/knowable.py`** |
| `scripts/phase5_isolation.py` | Correct savepoint-bound test isolation; documents why the earlier no-op-commit approach silently invalidated its own experiment | **Ported to `tests/conftest.py`** |
| `v2/` package (13 modules) | Content-addressed hashing, detached manifests, `fetch_run` with git_sha/argv/operator, authz-gated writes, DB immutability triggers, 246 tests | **Design ported wholesale** |
| `defensive/` package | "Records FACTS the pipeline already establishes and preserves the evidence it discards. It does not decide what a bar really is." | **Philosophy adopted** |
| `utils/candle_contract.py` | One rule in one place; every exemption carries a measured justification with a date and a symbol list | Concept reused; policy now fails **loud** |
| `engine/daily_series.py` | Picks one basis per symbol before fetching; collapses rows to sessions; every method takes an explicit `as_of` | API shape reused |
| `utils/symbols.py` | Idempotent normalisation; each rule quantifies the damage it prevents | Studied |
| `engine/event_classifier.py` | Two deterministic overrides on an LLM, both empirically justified (NSE label ORDER_WIN n=84 → **+1.053%** excess vs the LLM's label n=158 → **−0.245%**) | Reused in a later stage |
| The 98 forensic reports | Reports that attack their own predecessors and state what they could not verify | Preserved as evidence |

## 5. Reconciliation of prior V1 claims

| Prior finding | Verdict |
|---|---|
| Multiple daily candle anchors | **CONFIRMED — worse.** 14, not 3; and the duplicates *disagree on price*, which no report measured |
| 03:45 canonical / 18:30 legacy | **CONFIRMED** — but 5 bypass paths and ~25 readers ignore the resolver |
| Today's incomplete daily coverage | **CONFIRMED** (621 vs ~2,720 symbols) — plus 2026-09-14 missing and indistinguishable from a holiday |
| No pre-open table | **CONFIRMED** — and the data is fetched then discarded |
| No corporate-action table | **CONFIRMED** |
| Fundamentals current-state only | **CONFIRMED** — proven from schema; unaudited until now |
| FII/DII sparse | **CONFIRMED** — 50 rows total |
| No tick storage | **CONFIRMED** |
| Entity-resolution problems | **CONFIRMED — far worse.** Prior reports called the collisions *fixed*; `DOLLAR.NS` is still #1 |
| Live external calls during replay | **CONFIRMED — broader.** 9 of 11 tools, including two mandatory ones |
| Transaction-isolation repair | **CONFIRMED** — real and good, but `replay_news_pipeline.py` never adopted it |
| 5,082 `.BO` rows still present | **REFUTED / OUTDATED** — 0 remain |
| 00:00 series = 4,854,349 rows | **OUTDATED** — now 1,212,131 |
| "Alembic 0006, classification_trace NOT deployed" | **OUTDATED** — alembic is at `0008` and the table exists, but holds 0 rows |
| `premarket_news_queue` has no writer/reader | **REFUTED** — 11,977 rows, live |
| `SSEAnnouncement` never populated | **REFUTED** — 101 rows |
| Upstox data is RAW/UNADJUSTED | **CONTRADICTED** — three V1 reports take three positions. **Unresolved; open blocker B1** |

**Net: prior reports are directionally reliable but stale on specifics and they
systematically under-measure.** Anything older than ~two weeks must be
re-measured before it is relied on.

## 6. Verified Upstox capability for V2 (2026-09-22)

| Requirement | Upstox field | Where |
|---|---|---|
| IEP | `MarketFullFeed.iep` (11), `LTPC.iep` | WS v3 `full` |
| Indicative equilibrium quantity | `ieq` (13) | WS v3 `full` |
| Imbalance | `iiqTotal` (14), `iiqM` (15) | WS v3 `full` |
| Buy/sell quantities | `tbq` (9), `tsq` (10) | WS v3 `full` |
| Order book ladder | `marketLevel.bidAskQuote[]` — 5 rungs (`full`), 30 (`full_d30`, Plus only) | WS v3 |
| Pre-open status | `MarketInfo.preOpenSessionStatus` → PRE_OPEN_START / _M_END / _END | WS v3 |
| Reference price / prev close | `rp` (12) / `LTPC.cp` | WS v3 |
| Vendor timestamp | `FeedResponse.currentTs` | WS v3 |
| Instrument master | 80,127 rows; NSE_EQ 9,730; `instrument_type` carries the NSE series | `assets.upstox.com/...NSE.json.gz`, **public** |
| India VIX | `NSE_INDEX\|India VIX` | Upstox — no yfinance needed |

**Ruled out:** REST `/v2/market-quote/quotes` carries **none** of the
equilibrium fields. Pre-open is WebSocket-only.

**Not assumed — measured:** 351 tradeable NSE_EQ instruments carry `INF`-prefixed
ISINs (ETFs, incl. NIFTYBEES = `INF204KB14I2`) and 2 carry `IN9`. An "INE-only"
ISIN filter would silently drop all of them, so asset class is decided by
`segment` + `instrument_type`, never by the ISIN prefix.

## 7. Open blockers carried into V2

| ID | Blocker |
|---|---|
| **B0** | V1's Upstox token is expired (`401 UDAPI100050`). M1 requires a valid token |
| B1 | Daily-bar `knowable_at`: is the bar final at 15:30 IST or revised post-settlement? **Unmeasured** |
| B2 | Intraday vendor publication lag. **Unmeasured** |
| B3 | Is the account Upstox Plus? (`full_d30` = 30 rungs vs 5) |
| B4 | Does Upstox expose FII/DII at all? If not, stop and report — no vendor substitution |
| B5 | `full` subscription cap 2,000 vs ~2,200 pre-open-eligible equities |
| B6–B8 | Subscribe mode wire string; `iiqM` semantics; whether `iep`/`ieq` populate for non-`casEligible` instruments |
| B9 | Upstox `/v2/market/holidays` mixes trading/settlement/special holidays; 6 of 22 2026 entries were days NSE was **open** |
| B10 | Muhurat and Budget weekend sessions have non-standard windows |

## 8. Explicitly not verified

Docker container state (socket permission denied) · current V1 test pass/fail
counts (`pytest` deliberately not run — it writes logs and mutates settings) ·
diffs of the 20 modified V1 production files · the 45 deleted `docs/*.md` ·
`datasets/` artifacts (gitignored) · `autotrade-frontend/` · **no live-API
verification of any authenticated Upstox endpoint** (token expired).
