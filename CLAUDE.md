# Prajna: project instructions for Claude

Prajna is an NSE AI trading research system: an Upstox data stack, Stages 1–8, and a paper pipeline. The backend is in `backend/`.

## Hard rules
- **PAPER ONLY.** Never place, modify or cancel orders until the user explicitly authorises live trading in writing.
- Never touch or commit `frontend/` or `backend/app/api/`; another tool writes them.
- Never touch `/home/cis/windows/auto-trade-pro` (V1).
- Stored market data is Upstox only. FRED and US Treasury data are display-only. Yahoo is research-only: files only, never read by stages, models or the dashboard.
- Never print secrets: the DB password, the Upstox token, the Bedrock key.
- Never replay or backtest inside a research TEST window, and never take an interim look at a forward test. Do not bypass the Stage 1 gates.
- Back up before any production migration, to `/windows/prajna_archive`, and verify the sha256.
- Keep the git tree clean at 15:40 IST, because the paper job refuses a dirty tree.

## Trading doctrine (from all Zerodha Varsity modules + 604 Innerworth articles)
The full playbook is `docs/VARSITY_PLAYBOOK.md`, with line-level notes in `backend/var/research/varsity/varsity_notes.md` (local only, gitignored: the repo is public and the notes paraphrase copyrighted Varsity/Innerworth text). The AI-agent design is in `docs/STAGE4_AI_AGENT_DESIGN.md`. Apply these to any strategy, agent or evaluation work:

1. **Survival first.** Per-trade risk ≤ 1–2 % of reduced total equity; open risk ≤ ~3 %; daily loss limit, then halt. No martingale, no averaging down, no size-up after wins or losses. Recovery math: −L needs +L/(1−L).
2. **Every trade has four parts before entry:** entry, stop, target and holding period. RRR ≥ 1.5. The stop is set at entry, sits outside noise (≥ 1 ATR or σ·√days), and only tightens. If a proper stop breaks the RRR, skip the trade; never tighten the stop into noise. Size = risk ₹ / (entry − stop).
3. **Expectancy and payoff ratio net of all costs**, never hit rate alone. Model slippage per name. Overtrading kills net returns (Barber & Odean).
4. **Regime decides the tool.** Trend tools work in trends, range tools in ranges. Detect the regime first (ADX, breadth, multi-timeframe alignment, VIX); otherwise stand aside. "No trade" is a valid output, and there is no daily P&L target.
5. **Fade only noise.** Mean reversion applies to moves without news or fundamental change. Results and news moves are information. Results days are gated, and no position is carried across results.
6. **History repeats only when it does.** Every pattern, correlation or seasonality is a hypothesis: pre-register it, run it walk-forward against a placebo, take one look, and use rolling-window statistics. Correlations are computed on returns.
7. **Dynamic ≠ unfalsifiable.** An AI agent adapts its *outputs* (regime, allocation, vetoes), but the policy is a frozen, versioned object tested forward. An LLM may veto or shrink a trade, never create or enlarge one. Every LLM verdict must cite evidence ids. LLM-derived signals are validated **forward only**, because pre-training leaks history.
8. **Journal everything.** Record plan adherence. An "unjustified win" (a profitable deviation) is a violation. No hidden losses. On a losing streak, check first whether the regime changed, then de-risk by rule; decay → shadow → re-validate.
9. **Infra is risk.** No position without protection. If the system or vendor is down, there are no entries; if protection cannot be verified, flatten. Write the adverse-event responses in advance.
10. **No strategy works in every situation.** The goal is positive average expectancy plus small losses when standing aside, plus survival.

## Working conventions
- Query Postgres with `docker exec -i prajna-postgres sh -c 'psql -U "$POSTGRES_USER" -d prajna -At'` and a heredoc.
- Kill processes by exact PID only. Never edit a running runbook, and never edit code while pytest runs.
- The user writes in Hinglish; reply in Hinglish.
