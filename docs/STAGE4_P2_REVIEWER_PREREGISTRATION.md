# Stage 4 v2, phase P2: the LLM reviewer in shadow (pre-registration v1, FROZEN at `shadow review-freeze`)

**Status: FROZEN 2026-10-26** (reviewer `p2-reviewer-v1`). Forward start: 2026-10-27, the same as P1. The reviewer is frozen before any P1 shadow trade exists; the first trades are recorded on 2026-10-28 at 21:30.

**User decision 2026-10-26:** "p2 implement kro, bedrock key wahi rahegi". The existing Bedrock API key is kept, and no rotation is done.

**Parents:**
- `docs/STAGE4_AI_AGENT_DESIGN.md` L6;
- `docs/STAGE4_AGENTIC_INFRA.md` agent G;
- `docs/STAGE4_P1_SHADOW_PREREGISTRATION.md`.

PAPER/SHADOW ONLY. No order is ever touched.

## 1. Question

Can an LLM reviewer improve the four P1 shadow books by vetoing or shrinking trades? It reads only the evidence knowable at the signal time: stock news with its AI enrichment, results events, corporate actions, the macro calendar and the regime snapshots. The improvement must be net of costs and measured forward.

## 2. What the reviewer is

| Item | Frozen value |
|---|---|
| Model | `amazon.nova-pro-v1:0` on AWS Bedrock (the live news-AI model), temperature 0, max 400 output tokens |
| Prompt | `p2-prompt-v1` (`backend/app/shadow/review.py`). Every prompt's sha256 and every raw answer are stored |
| Inputs | **Trade:** strategy, symbol, company, sector, side, signal time, entry, stop, target, RRR, checklist, signal facts. **Evidence**, each with an id: stock news linked to the name with item and link `knowable_at` ≤ signal time and published within 48 h (at most 15), with the news-AI fields knowable by then; results events (intimation, outcome, estimate news) within ±3 days; non-zero corporate actions ex-dated in [T, T+7]; the macro calendar of T; regime snapshots of checkpoints ≤ the signal time |
| Blindness | The packet never contains the outcome: exit, exit reason, fills, charges, P&L. This is asserted in code and tested |
| Output | Closed JSON: `verdict` (PASS / SHRINK / VETO), `reason_codes` from a closed list (UNSEEN_MATERIAL_NEWS, RESULTS_OR_BOARD_MEETING, CORPORATE_ACTION, GOVERNANCE_FLAG, CIRCUIT_RISK, STALE_OR_CONFLICTING_DATA, STRATEGY_PRECONDITION_FAILED, MACRO_EVENT_WINDOW, OTHER), `evidence_ids`, `note` |
| Validation | Every cited id must be in the packet. SHRINK or VETO need ≥ 1 reason and ≥ 1 id. OTHER needs a note |
| Failsafe | INVALID, INVALID_EVIDENCE, ERROR or TIMEOUT is recorded with effective verdict **PASS**. A database CHECK enforces it. A failure never means "trade bigger" |
| Authority | It may only veto or shrink. It never creates a trade, enlarges one or moves a stop. In P2 nothing is applied: every trade is still simulated as P1 recorded it |
| Scope | Every P1 shadow trade, both real and placebo. Placebo reviews are the control |

**Why forward only.** An LLM's pre-training includes past news and outcomes, so a historical test would leak. Nova Pro's training data ends before the forward window, and the packets hold only information that was knowable at the signal time.

## 3. Metrics (computed only at the P1 looks)

**Applied book.** For each variant, the session book is recomputed with:
- VETO trades removed;
- SHRINK trades at 0.5 × size, so the net R is halved;
- PASS trades unchanged.

**Primary metric: veto value, V.** For each session, V = applied-book net R − recorded-book net R. It is averaged over sessions and **pooled over the four variants**, giving one test. The CI is a session block bootstrap (10,000 draws, seeded). The primary reading is at 10 bps slippage.

**Discrimination.** Mean net R of PASS trades minus mean net R of VETO trades, on real trades.
- **Control:** the same quantity on placebo trades. Vetoes on random names should not look systematically "right" through a shared market drift.

**Operational.**
- Verdict mix;
- the invalid and error rates;
- evidence counts;
- latency;
- cost.

**Looks:** the same two as P1, 60 and 250 forward sessions. There is no other look at verdict outcomes. The daily job prints the verdict mix only.

## 4. Gates

| Look | Rule | Consequence |
|---|---|---|
| 60 sessions | The 99.5 % CI upper bound of V < 0 | The reviewer is harmful: it becomes advisory only, and the version is retired |
| 250 sessions | The 95 % CI lower bound of V > 0 at 10 bps, discrimination > 0 on real trades, the placebo discrimination CI contains 0, and the invalid + error rate is ≤ 10 % | ACCEPTED: the reviewer may be applied in the P3 paper book (A2 autonomy) |
| otherwise | — | Advisory: recorded, not applied |

**Honesty.** A reviewer that vetoes 5–10 % of trades produces few vetoed trades. With about 2–6 real trades per session over four variants, that is roughly 30–150 vetoed trades by session 250. Only a large veto value will be detectable, and NOT_ACCEPTED is likely unless the effect is large. This is stated in advance.

## 5. Operations

- **Code:**
  - `backend/app/shadow/review.py`;
  - CLI `prajna shadow review [--commit]` and `prajna shadow review-freeze --forward-from D`;
  - runbook `ops/runbooks/shadow_review.sh`.
- **Schema:** migration 0029 adds `llm_reviewer` and `llm_review`, both append-only, with a SHADOW-only CHECK and a failsafe CHECK. The production backup is taken first and its sha256 verified.
- **Cron:** `15 22 * * 1-5`, after the 21:30 shadow job. It reviews every unreviewed trade of the policy from the forward start, so missed nights catch up.
- **Key:** `AWS_BEARER_TOKEN_BEDROCK` is read from `.env` into the environment only: never argv, never printed.
- **Cost:** about 2–3 k input tokens per review, about 30 reviews per session, so cents per day on Nova Pro.
- **Alerts:** Telegram on a refusal, or when every call of a run failed.
- **Tests** (`tests/shadow/test_review.py`, fake model, no network):
  - the schema and failsafe matrix;
  - the PIT packet: a later item is excluded, a late link is excluded, the 48 h window applies;
  - no outcome field in the packet;
  - the freeze is required;
  - one review per trade;
  - an error counts as PASS;
  - append-only and failsafe CHECKs;
  - a dry run writes nothing.
- **Live check, 2026-10-26:** one call on a synthetic packet (a made-up company and a regulatory-action headline) returned valid JSON: VETO, UNSEEN_MATERIAL_NEWS + STRATEGY_PRECONDITION_FAILED, citing `news:1`. No real trade was reviewed.

## 6. Left untouched

- P1 rules and books: the reviewer only annotates.
- E5, E6, the paper job, Stages 1–3, frontend/ and backend/app/api/.
