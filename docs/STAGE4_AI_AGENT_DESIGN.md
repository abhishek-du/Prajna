# Stage 4 v2: a dynamic, AI-assisted decision layer (design draft)

Status: DRAFT for the user's decision. Nothing in this document is built, scheduled or pre-registered.
Date: 2026-10-26. Context: E1–E5 and E5-H are closed. E5-H ended NOT_ACCEPTED (mean +3.3 bps, CI [−17.1, +23.9]). The gap fade is ACCEPTED-EXPLORATORY but fragile to slippage. E6 is a frozen paper monitor. The E5 forward test runs unchanged, with no interim look.
Companion: `docs/VARSITY_PLAYBOOK.md`, the trading doctrine distilled from all Zerodha Varsity modules.

## 0. The question, and the honest short answer

The request was: "Stage 4 should be intelligent and dynamic. Rules should not be static. An AI agent should look at everything, judge it and decide."

**What AI can do:**
- read text: news, filings and results, faster and more consistently than a human;
- turn that text into structured, time-stamped features;
- recognise the market state (regime) from many inputs at once;
- choose among several pre-tested strategies according to that state;
- review every proposed trade for reasons not to take it;
- write the post-mortem.

**What AI cannot do:**
- create an edge that is not in the data. Five pre-registered experiments found at most a small, fragile edge, and a model that "looks at everything" does not change that by itself;
- be evaluated honestly if its rules change whenever it likes. A policy that rewrites itself every day cannot be tested. Its results cannot be told apart from luck or hindsight, and Varsity and Innerworth repeat that this is the most common way traders fool themselves (overfitting, illusion of control, the "Holy Grail" regression).
- be backtested over the past when it is an LLM. An LLM's pre-training includes market history and news outcomes up to its knowledge cutoff, so an LLM shown 2020 news "knows" what happened next. LLM-derived signals can only be validated forward, on data after the model's cutoff and after the freeze date.

**So "dynamic" must mean this:** the decisions adapt to the market every session, but the policy that makes them is a frozen, versioned, tested object. This is not a contradiction. A thermostat is dynamic and its control law is fixed. Adaptivity lives in the inputs (the regime, "what is working today", news) and in bounded allocation rules. It never lives in unlogged intraday self-modification.

**A guarantee of profit in every situation is impossible.** No trader or system has one. The achievable goal has three parts:
- positive net expectancy on average across regimes;
- standing aside, with small losses, in the regimes where no tested edge exists;
- surviving every tail event.

Varsity says it plainly: "80 % money management, 20 % strategy", and "a crummy strategy with good money management can survive; a good strategy with poor money management cannot."

## 1. Architecture: bounded autonomy in layers

```
            ┌──────────────────────────────────────────────────────────────┐
  L0  HARD  │ paper-only switch · risk caps · daily loss halt · kill switch │  code, not AI,
  GUARDS    │ data-quality gates (Stage 1/2) · event-calendar gates       │  never overridable
            └──────────────────────────────────────────────────────────────┘
  L1 PERCEPTION   Stage 3 features (v5) + regime features + LLM text features (news-AI, results)
  L2 REGIME       session state: trend↑ / trend↓ / range / high-vol / event-wait / risk-off
                  + "what is working today" = shadow P&L of every library strategy at checkpoints
  L3 LIBRARY      specialist strategies, each a frozen spec with regime tags + evidence status
  L4 ALLOCATOR    regime × evidence × live record → risk budget per strategy (cash default)
  L5 CONSTRUCTOR  per-trade plan: entry, ATR/structure stop, target (S&R / R-multiple), time stop,
                  fixed-fraction size, RRR ≥ 1.5, liquidity, sector/correlation caps
  L6 AI REVIEWER  LLM devil's advocate: may VETO or SHRINK, never create or enlarge a trade
  L7 EXECUTION    paper simulator (Stage 7) + immutable decision journal (Stage 8)
  L8 LEARNING     offline only: weekly post-mortem → hypothesis queue → pre-registration
                  → forward test → promotion as a NEW policy version
```

### L0: hard guards (deterministic code; no model can override them)

These already exist in part in `app/paper/risk.py` and in the Stage 1 and 2 gates.
- Paper only. Orders are never placed, modified or cancelled, and this is enforced in code.
- Risk caps:
  - per-trade risk ≤ 1 % of reduced total equity;
  - open portfolio risk ≤ 3 %;
  - ≤ 3 names per sector;
  - maximum positions = 10;
  - cash reserve.
- Daily loss limit: the agent halts for the session and may not trade again that day. Varsity, Innerworth and Prajna doctrine agree on this, because it prevents revenge trading.
- Drawdown protocol:
  - after a drawdown of X % the size is halved;
  - after Y % trading halts until review;
  - size is never increased to "win it back". This is the martingale ban (Varsity M9 ch 11, Amaranth, Leeson).
- Data gate: if Stage 1 or 2 is not green for the session, or features are stale or LOW confidence, there is no new entry. This is the system's equivalent of Innerworth's rule "don't trade when you're not at your best".
- Event gate, driven by the calendar:
  - no new MIS entry in a stock on its results day unless the strategy declares results as its subject;
  - no position carried across results;
  - a session-level "event-wait" state for RBI policy, the Budget, F&O expiry and the FOMC night. The default there is reduced size or stand aside.
- Protection: every simulated position carries a stop from the moment of entry, and stops only tighten. If the system goes down, the rule is to flatten. In a live future this would mean a broker-side SL or bracket order.

### L1: perception, meaning features

These are deterministic and PIT-safe. Most already exist in Stage 3 v5. New families come from the playbook, and each is a hypothesis that must be tested:
- **Market regime:**
  - index trend (EMA 20/50, ADX(14) ≥ 25 trend versus < 20 range);
  - index position in its N-day range;
  - realised volatility and India VIX level and change (Upstox, if available);
  - gap size distribution at the open;
  - cross-sectional dispersion.
- **Breadth (Dow confirmation):**
  - % of the universe above its 20/50-DMA;
  - advance/decline;
  - % breaking a 20-day high or low;
  - Nifty, midcap and smallcap agreement.
- **Multi-timeframe alignment:** sign agreement of the daily, 60-minute and 15-minute trends.
- **Participation:** volume against the 10-day average; opening-range volume.
- **Stock context:**
  - ATR(14);
  - distance to time-tested S&R zones (≥ 3 touches, ≥ 2 weeks apart);
  - 52-week high/low proximity;
  - circuit-band proximity;
  - liquidity (median turnover, spread/impact proxy).
- **Events:**
  - results day (F4);
  - results surprise versus expectation (E6 rule inputs);
  - corporate actions;
  - scheduled macro events.
- **LLM text features** (news-AI enrichment is already live on Nova Pro):
  - per stock and session: has_material_news, direction, novelty, company-specific versus sector or macro, magnitude class, governance-red-flag;
  - always with `knowable_at` ≤ decision time, and with the model version and prompt hash stored.

### L2: the regime engine (the "dynamic" core)

It has two parts.
1. **State classifier:**
   - it runs pre-open (08:50–09:10) and at fixed intraday checkpoints (09:30, 10:30, 12:00, 13:30);
   - v0 is a transparent rule table on the L1 regime features, for example ADX, breadth, VIX percentile and the event calendar;
   - a statistical classifier (HMM or gradient boosting on realised next-period behaviour) comes only later, trained on data that never overlaps a test window.
2. **"What is working today":**
   - every library strategy runs in shadow on every session;
   - at each checkpoint, each strategy's realised shadow P&L so far (net of modelled costs) is a feature. This is the seasoned trader's habit, recorded in Innerworth, of watching which side and which factor is paying.
   - This is an input to the allocator, not a licence to chase. The allocator is shrunk heavily towards the prior, so that one good morning does not move much risk.

### L3: the strategy library

Each strategy is a specialist with a frozen spec. A spec holds:
- the hypothesis;
- the universe;
- the entry, stop, target and time stop;
- its regime tags, meaning where it is allowed to trade;
- its evidence status: CANDIDATE → EXPLORATORY → ACCEPTED → RETIRED.

Initial members, with their evidence today:

| Strategy | Playbook basis | Allowed regime | Evidence now |
|---|---|---|---|
| Gap fade, no news | Innerworth: fade noise moves, not information; M2 gaps | range / normal vol, no stock news, no results | ACCEPTED-EXPLORATORY (E4); slippage-fragile |
| Post-results drift (E6 rule) | M1 earnings vs expectation; M5 overreaction cases | any; event-driven | PAPER MONITOR, frozen; look ~Apr 2027 |
| Opening-range / breakout with volume + breadth | M2 Dow breakout rules; Innerworth breadth confirmation | trend↑ / trend↓ with breadth agreement | CANDIDATE |
| VWAP / intraday range reversion | M2 BB/RSI in ranges; M2 ch20 VWAP | range, ADX < 20, no news | CANDIDATE |
| Trend continuation (EMA / Supertrend, MTF aligned) | M2 MA systems: take every signal, few big winners | trend, ADX ≥ 25 | CANDIDATE |
| Sector leader → laggard catch-up | Innerworth #600 (index heavyweights lead) | trend days with sector move | CANDIDATE |
| Pairs / cointegration (positional) | M10 ch 8–12 | any; needs NRML/positional design | out of the MIS scope; needs approval |
| E5 ML ranking | Stage 4 E5 | n/a | NOT_ACCEPTED on 2020; forward test continues and cannot be used before its look |

**Rule:** only an ACCEPTED strategy receives normal risk. An EXPLORATORY strategy gets minimum size, for example 0.25 of normal. A CANDIDATE trades in shadow only, with zero size. This is the playbook's "start each strategy in its single best-evidenced niche".

### L4: the allocator (meta-policy)

The allocator is where "dynamic" becomes measurable. Its output each session and checkpoint is a risk budget per strategy, which sums to at most the portfolio cap. The default is **cash**.

- **v0, rule table (pre-registrable now):** a matrix of regime state × strategy → {0, ¼, ½, 1} × the strategy's evidence multiplier. Cells may be filled only from ex-ante reasoning, meaning the playbook regime table in §5 of the playbook, or from evidence outside any test window.
- **v1, conservative contextual bandit (later):**
  - Thompson sampling over strategies, with the regime as context;
  - priors set from pre-registered evidence and shrunk hard (for example, an effective prior weight of 60 sessions);
  - a per-strategy floor of 0 and a cap of 1;
  - it updates only after the session closes. There are no intraday weight jumps from one trade.
- **Never:** weights proportional to raw recent P&L (hot-hand chasing), leverage above the caps, or a strategy outside its regime tags.

### L5: the trade constructor (Varsity mechanics, in code)

For every candidate the constructor produces a full plan before anything is simulated. These are Varsity's four elements: entry, stop, target and holding period.
- **Stop:** the wider of
  - (a) the structure stop, meaning the pattern low/high or the broken level; and
  - (b) the volatility stop = entry ∓ max(1 × ATR, σ_daily × √holding_days × entry).
  - If the RRR with that stop is < 1.5, the trade is skipped. A stop is never placed inside noise; size is cut instead.
- **Size:** qty = (risk% × reduced total equity) / |entry − stop|, then capped by liquidity (≤ x % of the 5-minute ADV) and by the sector and correlation caps.
- **Target:** the next time-tested S&R zone, or an R-multiple. The exit policy is either a fixed target or partial at +1R with the stop moved to breakeven and a trailing remainder (ATR-step). It is frozen per strategy version and tested, not assumed.
- **Time stop:** the MIS square-off, plus a strategy-specific "should work quickly" rule (a Bollinger/VWAP reversion that does not work within N bars is exited).
- **Costs:** a name-specific spread and impact model plus the dated MIS cost tables. Every evaluation is net.

### L6: the AI reviewer (LLM devil's advocate), which may only reduce risk

This is the safest high-value use of an LLM. It encodes Gilbert's two-stage belief (Innerworth #495): we believe first and verify second, and under time pressure or fatigue the verification is skipped. A reviewer that never skips stage 2 is exactly what a human trader lacks.

- **Input:**
  - the trade plan (L5);
  - the last N hours of news items for the symbol and its sector, with ids and timestamps;
  - the event calendar;
  - circuit/ASM/GSM status if available;
  - the L1 features;
  - the strategy spec (hypothesis and exclusions).
- **Output:** a closed JSON schema, at temperature 0, with the model and version pinned and the prompt sha stored:
  `{verdict: PASS|SHRINK|VETO, reason_code: [...], evidence_ids: [...], note: str}`.
  The reason codes come from a fixed list:
  - UNSEEN_MATERIAL_NEWS;
  - RESULTS_OR_BOARD_MEETING;
  - CORPORATE_ACTION;
  - GOVERNANCE_FLAG;
  - CIRCUIT_RISK;
  - STALE_OR_CONFLICTING_DATA;
  - STRATEGY_PRECONDITION_FAILED (for example "fade only no-news gaps", but the gap has news);
  - MACRO_EVENT_WINDOW;
  - OTHER (needs a note).
- **Rules:**
  - every VETO must cite evidence ids. A rationale with no verifiable evidence is ignored, which is Innerworth's "testing your intuition";
  - the reviewer cannot create trades, raise size or move stops;
  - a timeout or error counts as PASS for shadow and as SHRINK for an explicitly approved mode, never as "trade bigger".
- **Measurement (decides whether the LLM earns its place):** every vetoed or shrunk trade is still simulated in shadow. Veto value = shadow P&L avoided minus P&L forgone, with a bootstrap CI over sessions. If the CI does not exclude zero after a pre-registered N, the reviewer is advisory only.
- **Reproducibility:** responses are stored. A replay reads the stored responses; it never calls the model again. This also makes the reviewer PIT-honest.

### L7: execution and journal

There is one immutable record per decision. It carries:
- policy version, regime state, allocator weights;
- the plan (entry, stop, target, size, RRR);
- the evidence (feature values, news ids);
- the reviewer verdict;
- the fills and exit reason;
- plan adherence: followed, or violated with a reason.

These are journal semantics from Innerworth:
- a profitable deviation is flagged as an **UNJUSTIFIED WIN** and counts as a violation;
- a loss with the plan followed is a **JUSTIFIED LOSS**;
- no loss is hidden, so nothing like an "error account" (Barings) can exist.

The daily "4:15 report" (Varsity M9 ch 10) holds:
- exposure, open risk, VaR/CVaR of the book;
- regime;
- plan adherence;
- costs and slippage against model.

### L8: learning loop (offline, versioned, never intraday)

- **Weekly LLM post-mortem** over the journal:
  - attribution by regime, strategy, time of day and sector;
  - clusters of losing trades with common factors (the Simon-versus-Jake rule: first ask whether the market condition changed);
  - suggestions are written into a hypothesis queue only.
- **Promotion path:** hypothesis → spec → pre-registration (with gates, MDE and windows) → forward shadow test → look → status change → new policy version. One strategy change per test window, so there is no strategy-hopping.
- **Edge-decay monitor:**
  - rolling 20/60-session net expectancy with a CI;
  - when it breaches a pre-registered floor, the strategy drops to SHADOW (size 0) until it is re-validated on new data. This is Innerworth #602: "when a method stops working, it can really stop working".

## 2. Why this answers "dynamic" without becoming "unfalsifiable"

| Need | How it is met | How it is tested |
|---|---|---|
| React to today's market | regime engine + checkpoints + "what is working today" | the allocator against a static allocation, forward |
| Use all information | L1 features + LLM text features | per-feature tests; LLM features only forward |
| Judgment / common sense | LLM reviewer with closed reasons and evidence | veto-value CI on shadow trades |
| Learn and improve | L8 versioned loop | each new version is its own pre-registered forward test |
| Never blow up | L0 guards | unit tests + incident drills; always on |

The unit of evaluation is the **policy version**: regime engine, library, allocator, constructor and reviewer together, frozen by sha. This mirrors how E5 was frozen.

## 3. Evaluation design (sketch; the full pre-registration comes later)

**Arms run in parallel, paper/shadow, on the same sessions:**
- A: bench_c0;
- B: static baseline (gap fade only, fixed size);
- C: dynamic policy without the reviewer;
- D: dynamic policy with the reviewer.

Shadow candidates also record every trade not taken.

**Primary metric:** per-session net return of the policy book in bps, versus B and A, paired by session; the Sharpe of session returns.

**Secondary metrics:**
- max drawdown;
- Sortino;
- up/down capture versus A;
- plan adherence;
- veto value;
- turnover and cost drag (Barber & Odean: the same gross return can produce a very different net).

**Honest sample size:** session returns have a standard deviation of roughly 60–100 bps (E5 experience). Detecting a +10 bps/session improvement at 80 % power takes on the order of 250–600 sessions, which is 1–2.5 years. A 60-session window can only catch large effects (≳ 25–30 bps) or show harm. This is stated up front so that no early result is over-read. Varsity's paradox of skill applies: in liquid large caps the residual edge is small and luck dominates short samples.

**Windows:** forward only, starting after the freeze. Never inside the E5 forward window's look rules, and never touching the E6 monitor's sessions as a backtest.

## 4. Phases and what each needs from the user

| Phase | Work | Risk to existing tests | Needs approval |
|---|---|---|---|
| P1 Regime + shadow library | regime features (breadth, ADX, MTF, VIX if available), rule-table classifier, shadow runner for library strategies, journal schema (migration) | none (shadow, new tables) | migration + cron line |
| P2 LLM reviewer, shadow | prompt/schema, Bedrock call at plan time, stored responses, veto-value report | none | Bedrock cost (≈ a few hundred calls/day), key rotation pending |
| P3 Pre-register policy v1 | allocator v0 rule table + constructor + guards; arms A–D; gates | none if windows are forward | the pre-registration itself |
| P4 Forward run | ≥ 60 sessions for a harm/large-effect check; longer for the confirmatory look | — | — |
| P5 (only if accepted) | bandit allocator v1 as a new version; any live pilot needs explicit written authorisation, scaled 10 → 25 → 50 → 100 % with gates | — | explicit live authorisation |

**What stays untouched:**
- the E5 forward test (no interim look; the look is around 2026-12-18);
- the E6 paper monitor;
- the frozen models and datasets;
- the Stage 1 gates;
- frontend/ and backend/app/api/.

## 5. Decisions for the user

1. Approve P1: regime features, the shadow library and the journal, as a new migration plus one cron line?
2. Approve P2: the LLM reviewer in shadow mode on the existing Bedrock Nova Pro setup, which needs the key rotation done first? Or another model?
3. Which CANDIDATE strategies should enter the shadow library first? Recommended: breakout + breadth, and VWAP range reversion, because they cover the trend and range regimes the gap fade does not.
4. Agree that "dynamic" means a frozen meta-policy that adapts its outputs, and that every change is a new tested version?
