# Prajna agentic AI infrastructure (design DRAFT)

**Status:** DRAFT, 2026-10-26; updated the same night.

**Built and running in shadow:**
- **P1:** regime engine + 4 shadow strategies, frozen, forward from 2026-10-27 (`docs/STAGE4_P1_SHADOW_PREREGISTRATION.md`).
- **P2:** the LLM reviewer, agent G, frozen, forward from 2026-10-27 (`docs/STAGE4_P2_REVIEWER_PREREGISTRATION.md`).

P3 onward still needs the approvals listed in §8.

**Builds on:**
- `docs/STAGE4_AI_AGENT_DESIGN.md` (layers L0–L8);
- `docs/VARSITY_PLAYBOOK.md`.

**Request (2026-10-26):** "an agentic AI that is smart enough to take decisions, make profit, and do research".

## 0. What "smart" means here

The system is smart in three ways, each measurable:
1. **It decides well inside a tested policy.**
   - It reads the session (regime, breadth, events, news) and routes risk to the strategies that work in that state.
   - It stands aside when none do.
   - It never breaks the risk laws.
2. **It researches continuously.**
   - It turns ideas (Varsity, journals, anomalies it notices) into pre-registered, falsifiable tests.
   - It runs those tests honestly: walk-forward, placebo, multiplicity-controlled, with one look.
   - It promotes only what survives.
3. **It knows when it is wrong.**
   - It monitors edge decay and drops a decaying strategy to shadow.
   - It explains every decision with evidence ids.
   - Its post-mortems feed the next round of research.

**How profit is meant to come:**
- a growing library of small, independently validated edges;
- each edge traded only in its regime, sized by risk and net of costs;
- losses avoided by guards and vetoes;
- survival through tails.

**No design guarantees profit.** What this one guarantees is that any claimed profit is real, meaning out-of-sample, net and not luck, and that a failed idea costs little.

**Why the system cannot improvise:** an LLM that "decides freely" cannot be evaluated: it is unfalsifiable, it leaks pre-training hindsight, and it cannot be reproduced. That is why intelligence is placed in perception, research and review, while the trading policy itself stays a frozen, versioned object.

## 1. The agents

Each agent below is listed with its job, its engine, its inputs and outputs, and what it may never do.

| # | Agent | Engine | Job | Writes | May never |
|---|---|---|---|---|---|
| A | **Orchestrator** | deterministic (cron + state machine) | the session lifecycle: data gates → perception → regime → decisions → review → simulate → journal → report; retries and catch-up | `agent_run` | skip a gate; run in a TEST window |
| B | **Perception** | deterministic features (Stage 3 v5 + regime features) + LLM text enrichment (news-AI, Nova Pro, live) | turn bars, filings and news into PIT features with `knowable_at` | Stage 3 tables, `news_ai_*`, `regime_snapshot` | use a value after the decision time |
| C | **Regime** | v0 rule table (P1); v1 statistical (HMM or GBM, trained outside every TEST window) | the session state + risk multiplier at checkpoints; "what is working today" from shadow P&L | `regime_snapshot` | change the rules intraday |
| D | **Strategy specialists** | deterministic frozen specs (S1, S2, gap fade, E6, …) | propose candidate trades with a full plan and a checklist score | `shadow_trade`, `shadow_skip` | trade outside their spec |
| E | **Portfolio / decision agent** | deterministic frozen policy: v0 regime × strategy rule table (from Playbook §5); v1 shrunk Thompson bandit | allocate the risk budget per strategy; choose the trades within the caps; cash is the default | `decision` | exceed the caps; chase raw recent P&L |
| F | **Risk guardian** | deterministic code (L0) | the final say: paper-only switch, 1 % / 3 % risk, sector 3, 10 positions, daily −3 % halt, drawdown 5 % / 10 %, event gate, data gate, kill switch | `guard_event` | be overridden by any agent |
| G | **Reviewer** | LLM (Claude Sonnet via Bedrock, or Nova Pro), temperature 0, pinned version, stored prompt sha | the devil's advocate on each planned trade: PASS, SHRINK or VETO, with closed reason codes and evidence ids | `llm_review` | create, enlarge or move a stop |
| H | **Execution** | paper simulator (Stage 7) | fills, costs, exits | `paper_*` | call a broker (no broker credentials exist in its environment) |
| I | **Journal / reporter** | numbers from SQL; the narrative from an LLM that is given only those numbers | the 4:15 report: exposure, risk, regime, adherence, costs against model, every claim tagged with a query id; a weekly post-mortem | `journal`, Telegram | invent a number; report forward-test P&L before its look |
| J | **Research agent** | LLM coding agent (Claude via the Agent SDK) inside a sandbox | turn ideas into specs → pre-registrations → tests; maintain the hypothesis queue | `research_*` (sandbox schema) | touch production tables, TEST windows or sealed data; change a live policy |
| K | **Auditor** | an independent LLM context + deterministic checks | review every research result before it is promoted: leakage, PIT, multiplicity, deviations from the pre-registration, cost realism | `research_audit` | be the same context as J |

**Humans approve:**
- every pre-registration freeze;
- every promotion to EXPLORATORY or ACCEPTED;
- every migration and cron line;
- any future live step, which needs written authorisation.

## 2. One session, end to end (A0/A1 autonomy)

```
06:30–08:40  data refresh, Stage 1/2 gates, CA refresh          (existing)
08:50        Perception: Stage 3 PRE_SESSION, news-AI, results calendar
09:05        Regime PRE (+ OPEN at 09:16 from the first 1m bar)  → state, risk multiplier
09:15–15:15  (live autonomy only, later) checkpoints 09:30/10:30/12:00/13:30
15:40        paper job (existing strategies)
19:00        1m bars land
21:30        shadow job: regime snapshots, S1/S2 + placebos, guards, skips   ← P1
21:45        (P2) reviewer on every shadow plan, stored; veto value measured later
22:00        (P3) decision agent: allocation + trades → paper, journal
next 16:20   reporter: 4:15-style report, health only for forward tests
weekly Sat   reporter post-mortem → research agent's hypothesis queue
```

Everything runs after the close on stored data (shadow and paper) until a policy earns intraday authority. Running after the close keeps the PIT rules checkable and means a crash costs nothing.

## 3. The research factory (agent J + auditor K)

This is where the system gets smarter over time. It is also where most AI trading systems fool themselves: run 1,000 backtests and one will look brilliant. The factory is built to stop that.

### 3.1 Data zones (enforced by DB roles and views, not by trust)

| Zone | What | Research agent access |
|---|---|---|
| EXPLORE | 1d data 2019-09 → 2024-12; 15m data 2022-01 → 2024-12, minus every registered TEST window (E1–E6) | read, unlimited, every query logged |
| VALIDATE | 2025-01 → 2026-06, minus the TEST windows | **sealed**; opened by the look ledger once per hypothesis version |
| FORWARD | sessions after each strategy's freeze | none; only the shadow and paper jobs write it; read at the pre-registered looks |
| TEST windows | the E1–E6 pre-registered windows | **none, ever** (doctrine: never replay inside a TEST window) |

The sandbox schema is `research_sb`. It has its own role: read-only on the canon views clipped to EXPLORE, and write access only to `research_*`. No `.env`, no Upstox token, and no broker code are in its environment.

### 3.2 The pipeline

```
idea card ─► spec (frozen numbers, Varsity basis, regime tags) ─► auditor pre-check
   ─► EXPLORE: walk-forward + placebo/permutation + cost sweep (0/5/10/20 bps)
   ─► gate E (pre-declared) ─► VALIDATE: one look, ledgered ─► gate V
   ─► human approves ─► shadow FORWARD as CANDIDATE (P1 machinery) ─► looks ─► status
```

**Idea sources:**
- the playbook's *(hypothesis)* rows (pullback-to-EMA, flag continuation, sector laggard, pre-event compression, …);
- the weekly post-mortem clusters;
- anomalies the perception layer flags;
- the user.

**Multiplicity control:**
- every backtest run in EXPLORE is written to a trial ledger;
- promotion uses the deflated Sharpe ratio / a Bonferroni-adjusted p over the number of trials *for that idea family*;
- an unlogged test is impossible, because the sandbox exposes the backtester only as a logged tool.

**Parameter discipline:**
- at most 3 parameter variants per idea;
- textbook values come first (as in P1);
- no tuning on VALIDATE.

**LLM-leak rule:**
- the research agent may *write code* for deterministic signals and test them on history;
- any signal that *uses an LLM's judgement* is tested only in FORWARD.

**Budgets:**
- ≤ 4 new hypotheses per month into VALIDATE;
- ≤ 2 new CANDIDATEs per month into FORWARD;
- a Bedrock cost cap per day, with a kill switch.

### 3.3 Promotion and demotion (one rule set for every strategy)

| Status | Size | Entry gate | Exit gate |
|---|---|---|---|
| CANDIDATE | 0 (shadow) | passes EXPLORE + VALIDATE, human approves | the 60-session look (99.5 % CI): harm → RETIRED |
| EXPLORATORY | 0.25 × normal in paper | 60-session look positive in regime, beats placebo at 10 bps | the 250-session look (95 %) |
| ACCEPTED | normal (1 % risk) × regime multiplier | 250-session look: H-in-regime + H3 + placebo at 10 bps | the decay monitor: rolling 60-session net-R CI below its floor → back to shadow |
| RETIRED | 0 | — | only a new version can return, with a fresh window |

## 4. The decision policy (agent E), version path

- **v0 (P3, pre-registered):** the allocation is a rule table (Playbook §5) × the evidence status × the L0 multipliers. Example cells:
  - `TREND_UP` → S1 longs 1.0, S2 0;
  - `RANGE` → S2 0.5, S1 0;
  - `SHOCK` → everything 0 except protective exits;
  - `MIXED` → cash.
  It is transparent and testable against the static arms (bench_c0, gap fade only).
- **v1 (only after v0 has a forward record):** a contextual Thompson bandit, with the regime as context:
  - priors from the accepted evidence, shrunk to a weight of 60 sessions;
  - it updates once per session after the close;
  - the weight per strategy is capped at 1 × its status size.
  This is "learning which tool works in which weather" with an audit trail. It is a new version with its own forward test.
- **Never:** free-form LLM allocation, intraday self-modification, weights proportional to the last few days' P&L, or size-up after losses.

## 5. Infrastructure (what gets built, in order)

| Component | Detail |
|---|---|
| Schemas | `shadow_*` (P1); `llm_review`, `llm_call` (P2); `decision`, `journal`, `guard_event` (P3); `research_sb.*`, `research_trial`, `research_audit`, `look_ledger` (P4) |
| LLM gateway | one module that calls Bedrock: pinned model ids, temperature 0, JSON-schema validation, prompt and response sha stored, retries, a daily cost cap, a kill switch; no tool access to the DB except through the pre-built read-only evidence packet |
| Agent runtime (J, K) | Claude Agent SDK in a sandboxed process; a whitelist of tools (`sql_explore`, `run_backtest`, `write_spec`, `read_docs`); no shell, no network beyond Bedrock |
| Evidence packets | deterministic JSON built per decision: features, news ids, calendar, spec. The LLM sees only this, so every claim can be traced to an id |
| Reproducibility | every agent run has a run id, code sha, policy sha and input sha; a replay reads the stored LLM outputs and never re-calls the model |
| Observability | an agent health table and Telegram alerts on errors or refusals; the dashboard (read-only) gains panels only after their forward looks |
| Security | secrets never enter any LLM context; no broker credential exists anywhere; order placement is absent from the code until written authorisation |

## 6. Autonomy levels

| Level | The agent may | Status |
|---|---|---|
| A0 Shadow | record what it would do | P1, starting now |
| A1 Paper decisions | allocate and trade the paper book within L0 | after P3's pre-registration |
| A2 Paper + reviewer | A1 plus veto and shrink | after P2 has a veto-value record |
| A3 Live pilot | a minimum live size, scaled 10 → 25 → 50 → 100 % by gates | **only with the user's written authorisation**, and only for ACCEPTED strategies |

## 7. Roadmap

| Phase | What | Earliest |
|---|---|---|
| P1 | regime engine + shadow S1/S2 (core + strict) + placebos | **BUILT, FROZEN 2026-10-26**; forward from 2026-10-27; cron 21:30 |
| P2 | LLM reviewer (Nova Pro, same key per user) in shadow on every P1 trade | **BUILT, FROZEN 2026-10-26**; forward from 2026-10-27; cron 22:15 |
| P3 | decision agent v0 + journal + 4:15 report, paper (A1) | pre-registration in November; forward from December |
| P4 | research factory (J + K, data zones, ledgers) | December; its first hypotheses come from the playbook rows |
| P5 | the first looks: P1 at 60 sessions (about late January 2027); E5 (about 2026-12-18); E6 (about April 2027) | — |
| P6 | bandit allocator v1, or a live pilot | only after P5 evidence, plus written authorisation for live |

## 8. Decisions for the user

1. Agree with this architecture: intelligence in perception, research and review; a frozen, versioned decision policy; humans approve freezes and promotions.
2. Accept the four **PRAJNA DEFAULT** numbers in P1 pre-registration §1, or change them now:
   - the 1-hour "not working" time stop;
   - the VIX spike threshold (percentile ≥ 90 or a +20 % day);
   - breadth collapse at A/D ≤ 0.2;
   - the 3 % no-news proxy.
3. P2 and P4 need LLM access. Rotate the Bedrock key, then choose the reviewer and research models: Claude Sonnet via Bedrock is recommended for both, with Nova Pro kept for news enrichment.
