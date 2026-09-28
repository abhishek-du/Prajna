"""Market-context features (diagram group 5).

  index trend      NIFTY 50 / NIFTY BANK: ret_1d, ret_5d, close_to_sma_50 (PROPOSED window)
  india_vix        level (last close) and 5-session change in points (PROPOSED window)
  fii/dii flows    net cash-market flow (buy - sell, INR crore) of the snapshot's
                   PREVIOUS TRADING SESSION, and the sum of the last 5 observed days
                   ending at that session (decision FII-DII-STALENESS: if the latest
                   observation is not the previous session, MISSING_INPUT - an older
                   day is never relabelled as the current one)
  global           return between the two latest CONFIRMED labels of each global
                   instrument (revised/placeholder/unconfirmed labels never reach here)
  sector_rs_20     stock ret_20 - median ret_20 of its point-in-time sector (>= 3 members)
Market regime (bull/bear/sideways) and "sector/market events": UNKNOWN (no
definition exists in any source).
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date
from typing import Any

from app.features.compute import (
    DIVISION_UNDEFINED,
    INSUFFICIENT_HISTORY,
    MALFORMED_INPUT,
    MISSING_INPUT,
    Result,
    miss,
    ok,
)


def vix_change(closes: list[float], n: int = 5) -> Result:
    if len(closes) < n + 1:
        return miss(INSUFFICIENT_HISTORY)
    return ok(closes[-1] - closes[-1 - n])


def net_flows(rows: list[dict[str, Any]], who: str) -> dict[date, float] | None:
    """{observation_date: buy - sell} of `who` (FII / DII) in the NSE cash market.
    None when a day has only one side (never guessed)."""
    by: dict[date, dict[str, float]] = defaultdict(dict)
    for r in rows:
        code = r.get("series_code") or ""
        if not code.startswith(f"{who}|NSE_EQ|CASH|1D|"):
            continue
        side = code.rsplit("|", 1)[-1]
        if side in ("buy_amt", "sell_amt"):
            try:
                by[r["observation_date"]][side] = float(r["value"])
            except (TypeError, ValueError, KeyError):
                return None
    out = {}
    for d, v in by.items():
        if set(v) != {"buy_amt", "sell_amt"}:
            return None
        out[d] = v["buy_amt"] - v["sell_amt"]
    return out


def flow(rows: list[dict[str, Any]], who: str, n: int, previous_session: date | None) -> Result:
    """Net flow of the previous trading session (n=1) or the sum of the last n observed
    days ending AT the previous session. `rows` are already point in time (knowable
    before as_of); a latest observation that is not the previous session - late or
    missing publication - is MISSING_INPUT, never an older day relabelled."""
    f = net_flows(rows, who)
    if f is None:
        return miss(MALFORMED_INPUT)
    if not f or previous_session is None or max(f) != previous_session:
        return miss(MISSING_INPUT)
    days = sorted(f)[-n:]
    if len(days) < n:
        return miss(INSUFFICIENT_HISTORY)
    return ok(sum(f[d] for d in days))


def global_ret(closes: list[float]) -> Result:
    if len(closes) < 2:
        return miss(INSUFFICIENT_HISTORY)
    return ok(closes[-1] / closes[-2] - 1) if closes[-2] > 0 else miss(DIVISION_UNDEFINED)


def sector_rs(stock_ret: float | None, member_rets: list[float]) -> Result:
    if stock_ret is None:
        return miss(INSUFFICIENT_HISTORY)
    if len(member_rets) < 3:
        return miss(INSUFFICIENT_HISTORY)
    return ok(stock_ret - statistics.median(member_rets))
