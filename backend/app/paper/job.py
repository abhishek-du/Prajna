"""Stage 7 step 3: the paper job. strategy -> TargetList -> Stage 6 limits -> simulate ->
record, per session, in session order (the risk state of a day uses the days before it).

`replay` runs past sessions once by hand (a pipeline test). The daily schedule is NOT
installed: a cron line needs the user's approval. A session's 1d bars must be stored
(the next morning), so the job for d runs on d + 1 at the earliest.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.paper import risk as RK
from app.paper import sim, store
from app.paper import strategies as ST


STRATEGY_LIMITS = {"bench_c0": RK.Limits(max_drawdown_halt=float("inf"),
                                         daily_loss_halt=float("inf"))}


async def state(s: AsyncSession, strategy: str, before: _dt.date,
                capital: float) -> RK.State:
    pnl = [float(r) for r in (await s.execute(text("""select d.pnl_inr from paper_day d
        join paper_run r using (run_id) where r.strategy = :s and d.session_date < :b
        order by d.session_date"""), {"s": strategy, "b": before})).scalars()]
    cum, peak = 0.0, 0.0
    for p in pnl:
        cum += p
        peak = max(peak, cum)
    return RK.State(capital, drawdown_inr=peak - cum, last_day_pnl_inr=pnl[-1] if pnl else 0.0)


async def run_session(s: AsyncSession, m: ST.Market, strategy: str, session: _dt.date, *,
                      limits: RK.Limits | None = None, cfg: sim.Config | None = None,
                      commit: bool = False, token: str | None = None,
                      code_git_sha: str = "unknown") -> dict[str, Any]:
    if strategy not in ST.STRATEGIES:
        raise store.PaperRefused(f"unknown strategy {strategy} ({sorted(ST.STRATEGIES)})")
    cfg = cfg or sim.Config()
    limits = limits or STRATEGY_LIMITS.get(strategy, RK.Limits())
    tl = ST.STRATEGIES[strategy](m, session)
    approved, decisions = RK.apply(tl, ST.context(m, session),
                                   await state(s, strategy, session, cfg.capital_inr), limits)
    return await store.simulate_session(
        s, strategy, session, approved.keys, cfg, commit=commit, token=token,
        code_git_sha=code_git_sha, target_list=tl.to_dict(), risk=decisions,
        risk_limits=limits.to_dict())


async def replay(s: AsyncSession, m: ST.Market, strategy: str, start: _dt.date,
                 end: _dt.date, **kw: Any) -> list[dict[str, Any]]:
    """Every loaded session in [start, end], in order; a refused session stops the
    replay (nothing later is simulated on a broken risk state)."""
    out = []
    for d in (x for x in m.days if start <= x <= end):
        r = await run_session(s, m, strategy, d, **kw)
        out.append({k: r[k] for k in ("session_date", "status", "targets", "filled",
                                      "pnl_inr", "charges_inr")}
                   | {"rejected": sum(1 for x in r["risk"] if x["decision"] == "REJECTED")})
    return out


FORWARD_FROM = _dt.date(2026, 10, 16)    # after every research TEST window (2026-10-16 rule)


async def pending(s: AsyncSession, strategy: str,
                  floor: _dt.date = FORWARD_FROM) -> tuple[_dt.date, _dt.date] | None:
    """The sessions still to simulate: after the strategy's last recorded session (or from
    floor) through the latest session whose 1d bars are stored (the Nifty 50 bar). A
    recorded day is never re-run, so a later vendor revision cannot refuse the job."""
    last = (await s.execute(text("""select max(session_date) from paper_run
        where strategy = :s"""), {"s": strategy})).scalar()
    ready = (await s.execute(text("""select max(market_date) from canon_market_bar
        where instrument_key = 'NSE_INDEX|Nifty 50' and timeframe = '1d'"""))).scalar()
    first = (await s.execute(text("""select min(session_date) from trading_session
        where is_trading_day and session_date > :a and session_date >= :f"""),
        {"a": last or _dt.date.min, "f": floor})).scalar()
    if ready is None or first is None or first > ready:
        return None
    return first, ready
