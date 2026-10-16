"""Stage 8: paper performance, benchmarks, alerts and drift. Read-only.

Per session: the strategy's paper return (P&L / capital), the Nifty 50 open -> close
return (the canonical 1d bar) and, when recorded, the baseline_c0 paper return (the same
universe, costs and fills, picked at random: the fair benchmark).
Summary: cumulative curve, total return, max drawdown, annualised Sharpe (252), hit rate,
cost share (charges / gross P&L magnitude), fill rate, missing sessions.
Alerts (thresholds in Thresholds): missing session, no fills, drawdown beyond the limit,
cost share above the limit. Drift: PSI of a score distribution against a reference.
Nothing here is a profitability claim; the report says so.
"""

from __future__ import annotations

import datetime as _dt
import math
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

NIFTY = "NSE_INDEX|Nifty 50"
BENCH_STRATEGY = "bench_c0"         # never halted (job.STRATEGY_LIMITS)
DISCLAIMER = "PAPER ONLY. Simulated fills; not a profitability claim."


@dataclass(frozen=True)
class Thresholds:
    max_drawdown: float = 0.05           # of capital
    max_cost_share: float = 0.5          # charges / |gross P&L|
    psi_alert: float = 0.25              # conventional "significant shift"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def daily(s: AsyncSession, strategy: str, start: _dt.date,
                end: _dt.date) -> list[dict[str, Any]]:
    rows = (await s.execute(text("""
        with sess as (select session_date from trading_session
                      where is_trading_day and session_date between :a and :b),
             mine as (select d.*, (r.config->>'capital_inr')::float capital from paper_day d
                      join paper_run r using (run_id) where r.strategy = :s),
             bench as (select d.session_date, d.pnl_inr, (r.config->>'capital_inr')::float cap
                       from paper_day d join paper_run r using (run_id)
                       where r.strategy = :c),
             nifty as (select market_date, close / open - 1 r from canon_market_bar
                       where instrument_key = :n and timeframe = '1d'
                         and market_date between :a and :b)
        select x.session_date, m.pnl_inr, m.charges_inr, m.turnover_inr, m.targets, m.filled,
               m.capital, n.r nifty, b.pnl_inr / b.cap c0
        from sess x left join mine m using (session_date)
        left join nifty n on n.market_date = x.session_date
        left join bench b on b.session_date = x.session_date order by 1"""),
        {"a": start, "b": end, "s": strategy, "c": BENCH_STRATEGY, "n": NIFTY})).all()
    return [{"session_date": r.session_date, "recorded": r.pnl_inr is not None,
             "pnl_inr": None if r.pnl_inr is None else float(r.pnl_inr),
             "ret": None if r.pnl_inr is None else float(r.pnl_inr) / r.capital,
             "charges_inr": None if r.charges_inr is None else float(r.charges_inr),
             "turnover_inr": None if r.turnover_inr is None else float(r.turnover_inr),
             "targets": r.targets, "filled": r.filled,
             "nifty_oc": None if r.nifty is None else float(r.nifty),
             "c0": None if r.c0 is None else float(r.c0)} for r in rows]


def max_drawdown(rets: list[float]) -> float:
    """Of the cumulative (additive, fraction of capital) curve, >= 0."""
    cum, peak, dd = 0.0, 0.0, 0.0
    for r in rets:
        cum += r
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    return dd


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rec = [r for r in rows if r["recorded"]]
    rets = [r["ret"] for r in rec]
    traded = [r["ret"] for r in rec if r["targets"]]
    first = min((r["session_date"] for r in rec), default=None)
    sd = float(np.std(rets, ddof=1)) if len(rets) > 1 else 0.0
    gross = sum(abs((r["pnl_inr"] or 0) + (r["charges_inr"] or 0)) for r in rec)
    tgt = sum(r["targets"] or 0 for r in rec)

    def tot(k: str) -> float | None:
        v = [r[k] for r in rec if r[k] is not None]
        return float(sum(v)) if v else None
    return {"sessions": len(rows), "recorded": len(rec),
            # a session is missing only after the strategy's first day and once its
            # bars exist (the Nifty bar: stored the next morning)
            "missing": [str(r["session_date"]) for r in rows if not r["recorded"]
                        and first is not None and r["session_date"] > first
                        and r["nifty_oc"] is not None],
            "traded_sessions": len(traded),
            "total_return": float(sum(rets)) if rets else None,
            "mean_daily_bps": float(np.mean(rets)) * 1e4 if rets else None,
            "sharpe_annual": float(np.mean(rets)) / sd * math.sqrt(252) if sd > 0 else None,
            "max_drawdown": max_drawdown(rets),
            "hit_rate": sum(1 for x in traded if x > 0) / len(traded) if traded else None,
            "charges_inr": tot("charges_inr"), "turnover_inr": tot("turnover_inr"),
            "cost_share": (tot("charges_inr") or 0) / gross if gross else None,
            "fill_rate": sum(r["filled"] or 0 for r in rec) / tgt if tgt else None,
            "nifty_oc_total": tot("nifty_oc"), "c0_total": tot("c0"),
            "disclaimer": DISCLAIMER}


def alerts(rows: list[dict[str, Any]], summ: dict[str, Any],
           th: Thresholds | None = None) -> list[str]:
    th = th or Thresholds()
    out = [f"missing_session {d}" for d in summ["missing"]]
    out += [f"no_fills {r['session_date']}" for r in rows
            if r["recorded"] and (r["targets"] or 0) > 0 and not r["filled"]]
    if summ["max_drawdown"] > th.max_drawdown:
        out.append(f"drawdown {summ['max_drawdown']:.2%} > {th.max_drawdown:.0%}")
    if summ["cost_share"] is not None and summ["cost_share"] > th.max_cost_share:
        out.append(f"cost_share {summ['cost_share']:.0%} > {th.max_cost_share:.0%}")
    return out


def psi(reference: list[float], current: list[float], bins: int = 10) -> float | None:
    """Population stability index of current against reference (reference deciles)."""
    ref = np.asarray([x for x in reference if x is not None and math.isfinite(x)])
    cur = np.asarray([x for x in current if x is not None and math.isfinite(x)])
    if len(ref) < bins or len(cur) == 0:
        return None
    edges = np.unique(np.quantile(ref, np.linspace(0, 1, bins + 1)))
    if len(edges) < 3:
        return None
    edges[0], edges[-1] = -np.inf, np.inf
    eps = 1e-4
    p = np.histogram(ref, edges)[0] / len(ref) + eps
    q = np.histogram(cur, edges)[0] / len(cur) + eps
    return float(np.sum((q - p) * np.log(q / p)))


async def scores(s: AsyncSession, strategy: str, start: _dt.date, end: _dt.date) -> list[float]:
    """The scores of a strategy's targets (from the stored target lists)."""
    rows = (await s.execute(text("""select (e->>'score')::float from paper_run r,
        jsonb_array_elements(r.target_list->'entries') e
        where r.strategy = :s and r.session_date between :a and :b
          and e->>'score' is not null"""), {"s": strategy, "a": start, "b": end})).scalars()
    return list(rows)


def text_report(strategy: str, start: _dt.date, end: _dt.date, summ: dict[str, Any],
                al: list[str]) -> str:
    def pct(x: float | None, signed: bool = True) -> str:
        return "n/a" if x is None else (f"{x:+.2%}" if signed else f"{x:.0%}")
    return "\n".join([
        f"Prajna PAPER report {strategy} {start}..{end}",
        f"sessions {summ['recorded']}/{summ['sessions']}, return {pct(summ['total_return'])}"
        f" (Nifty o->c {pct(summ['nifty_oc_total'])}, C0 {pct(summ['c0_total'])})",
        f"max drawdown {summ['max_drawdown']:.2%}, hit rate {pct(summ['hit_rate'], False)}, "
        f"fill rate {pct(summ['fill_rate'], False)}",
        f"alerts: {'; '.join(al) if al else 'none'}",
        DISCLAIMER])
