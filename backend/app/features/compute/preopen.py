"""Pre-open features (diagram group 6), PRE_OPEN snapshot only.

From the latest pre-open tick knowable before as_of:
  preopen_gap_pct          IEP / previous close - 1  (the diagram's "IEP vs previous
                           close" and "gap up/down %": the open itself is not
                           knowable before 09:15, the IEP is its indication)
  preopen_imbalance        (total buy qty - total sell qty) / (total buy + total sell)
  preopen_ieq              indicative equilibrium quantity
  preopen_ieq_to_avg_vol   ieq / average daily volume of the last 20 sessions
"""

from __future__ import annotations

from typing import Any

from app.features.compute import DIVISION_UNDEFINED, MISSING_INPUT, Result, miss, ok


def _num(tick: dict[str, Any] | None, k: str) -> float | None:
    if not tick or tick.get(k) is None:
        return None
    try:
        return float(tick[k])
    except (TypeError, ValueError):
        return None


def gap_pct(tick: dict[str, Any] | None, prev_close: float | None) -> Result:
    iep = _num(tick, "iep")
    if iep is None or iep <= 0 or prev_close is None:
        return miss(MISSING_INPUT)
    return ok(iep / prev_close - 1) if prev_close > 0 else miss(DIVISION_UNDEFINED)


def imbalance(tick: dict[str, Any] | None) -> Result:
    b, s = _num(tick, "tbq"), _num(tick, "tsq")
    if b is None or s is None:
        return miss(MISSING_INPUT)
    return ok((b - s) / (b + s)) if b + s > 0 else miss(DIVISION_UNDEFINED)


def ieq(tick: dict[str, Any] | None) -> Result:
    q = _num(tick, "ieq")
    return ok(q) if q is not None else miss(MISSING_INPUT)


def ieq_to_avg_volume(tick: dict[str, Any] | None, avg_volume: float | None) -> Result:
    q = _num(tick, "ieq")
    if q is None or avg_volume is None:
        return miss(MISSING_INPUT)
    return ok(q / avg_volume) if avg_volume > 0 else miss(DIVISION_UNDEFINED)
