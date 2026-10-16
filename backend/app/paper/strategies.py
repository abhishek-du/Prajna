"""Strategy adapters: a session's TargetList from the stored daily bars (Stage 5 side).

The baselines use the E4 rules themselves (app.training.e4: universe, predictors), so a
validated E4 predictor plugs in unchanged. They are PIPELINE BASELINES, not strategies
with a claimed edge:
  baseline_gap_fade  E4 arm P: the K names with the largest down-gap (buy at the open)
  baseline_c0        K names drawn at random from the same universe (seeded by the date)

Knowability: the rules read close/volume of sessions < d and the official open of d,
known at 09:15 IST (decision_at). Live, the open comes from the pre-open auction (IEP);
in replay it is read from the stored 1d bar of d, which lands the next morning, so the
paper job for d runs after that. Bars are pit.bars_adjusted at one cutoff, as in the E4
dataset: the rules use ratios (gap, turnover), which a later split does not change.
The research-only suspect-on-d mask is NOT applied (it reads close(d): not knowable).
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Callable
from typing import Any

import numpy as np
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.canon import pit
from app.core.clock import IST
from app.paper.targets import OPEN_IST, Target, TargetList
from app.training import e3 as E3
from app.training import e4 as E4

FIELDS = ("open", "high", "low", "close", "volume")
HISTORY_SESSIONS = 320           # > E3.MIN_HISTORY (260) valid closes plus slack


class Market:
    """Daily series of every included NSE_EQ instrument over a session range."""

    def __init__(self, days: list[_dt.date], series: dict[str, dict[str, list]],
                 sectors: dict[str, str | None]):
        self.days, self.series, self.sectors = days, series, sectors
        self.index = {d: i for i, d in enumerate(days)}
        self.suspect = {k: E3.suspect_sessions(s) for k, s in series.items()}

    def d(self, session: _dt.date) -> int:
        if session not in self.index:
            raise KeyError(f"{session} is not a loaded trading session")
        return self.index[session]


async def load_market(s: AsyncSession, first: _dt.date, last: _dt.date, *,
                      cutoff: _dt.datetime, keys: list[str] | None = None) -> Market:
    """Sessions from HISTORY_SESSIONS before `first` through `last`."""
    days = list((await s.execute(text("""
        (select session_date from trading_session where is_trading_day and session_date < :a
           order by 1 desc limit :n)
        union select session_date from trading_session
           where is_trading_day and session_date between :a and :b order by 1"""),
        {"a": first, "b": last, "n": HISTORY_SESSIONS})).scalars())
    rows = (await s.execute(text("""select instrument_key, sector from canon_instrument
        where included and segment = 'NSE_EQ' order by 1"""))).all()
    sectors = {r.instrument_key: r.sector for r in rows}
    want = keys if keys is not None else list(sectors)
    idx = {d: i for i, d in enumerate(days)}
    series: dict[str, dict[str, list]] = {}
    for k in want:
        r = await pit.bars_adjusted(s, k, "1d", cutoff, start=days[0], end=days[-1],
                                    allow_low_confidence=True)
        cols = {f: [None] * len(days) for f in FIELDS}
        for b in r["rows"]:
            i = idx.get(b["market_date"])
            if i is not None:
                for f in FIELDS:
                    cols[f][i] = None if b.get(f) is None else float(b[f])
        series[k] = cols
    return Market(days, series, {k: sectors.get(k) for k in want})


def _decision_at(session: _dt.date) -> _dt.datetime:
    return _dt.datetime.combine(session, OPEN_IST, tzinfo=IST)


def _list(name: str, session: _dt.date, picks: list[tuple[str, float | None]],
          meta: dict[str, Any]) -> TargetList:
    return TargetList(name, session, _decision_at(session),
                      tuple(Target(k, i + 1, sc) for i, (k, sc) in enumerate(picks)),
                      source=f"app.paper.strategies.{name}", meta=meta).validate()


def gap_fade(m: Market, session: _dt.date, k: int = E4.K) -> TargetList:
    d = m.d(session)
    u = E4.eligible(m.series, d, m.suspect)
    scored = sorted(((E4.gap_fade(m.series[r[0]], d), r[0]) for r in u),
                    key=lambda x: (-(x[0] if x[0] is not None else -np.inf), x[1]))
    picks = [(key, sc) for sc, key in scored if sc is not None][:k]
    return _list("baseline_gap_fade", session, picks,
                 {"universe": len(u), "rule": "e4.gap_fade arm P", "k": k})


def c0(m: Market, session: _dt.date, k: int = E4.K) -> TargetList:
    d = m.d(session)
    u = [r[0] for r in E4.eligible(m.series, d, m.suspect)]
    rng = np.random.default_rng([20261016, session.toordinal()])
    picks = [(u[i], None) for i in sorted(rng.choice(len(u), size=min(k, len(u)),
                                                     replace=False))] if u else []
    return _list("baseline_c0", session, picks,
                 {"universe": len(u), "rule": "random K of the e4 universe", "k": k})


STRATEGIES: dict[str, Callable[[Market, _dt.date], TargetList]] = {
    "baseline_gap_fade": gap_fade, "baseline_c0": c0}


def context(m: Market, session: _dt.date) -> dict[str, dict[str, Any]]:
    """What the risk layer may know at 09:15 of the session, per key."""
    d = m.d(session)
    out = {}
    for k, s in m.series.items():
        out[k] = {"sector": m.sectors.get(k), "prev_close": s["close"][d - 1] if d else None,
                  "turnover": E3.median_turnover(s, d - 1) if d else None}
    return out
