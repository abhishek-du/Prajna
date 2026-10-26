"""Candlestick checks and support/resistance zones (Varsity M2), PURE.

Candles (one bar; doji-like bars with no body never qualify):
  strong_bull / strong_bear   body >= 50 % of the range and the close in the top / bottom
                              25 % of it (a marubozu-like breakout candle)
  hammer / shooting_star      lower / upper wick >= 2 x the body, the opposite wick <= body
  engulfing (bull / bear)     the bar's body covers the previous bar's opposite-colour body

S/R zones from daily bars of sessions < T: pivot highs and lows (the extreme of a
2w + 1 session window, complete before T), clustered greedily in price order within a
relative tolerance; a zone needs >= min_touches pivots whose first and last are >= span
sessions apart. The zone price is the cluster mean.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.shadow.bars import IBar
from app.shadow.spec import SR


def _parts(b: IBar) -> tuple[float, float, float, float]:
    body = abs(b.close - b.open)
    rng = b.high - b.low
    upper = b.high - max(b.open, b.close)
    lower = min(b.open, b.close) - b.low
    return body, rng, upper, lower


def strong(b: IBar, side: int, body_min: float, close_pos: float) -> bool:
    body, rng, _, _ = _parts(b)
    if rng <= 0 or body <= 0 or body < body_min * rng:
        return False
    if side > 0:
        return b.close > b.open and (b.close - b.low) / rng >= close_pos
    return b.close < b.open and (b.high - b.close) / rng >= close_pos


def reversal(b: IBar, prev: IBar | None, side: int, wick_min: float) -> str | None:
    """The bullish (side +1) or bearish (-1) reversal pattern on b, or None."""
    body, rng, upper, lower = _parts(b)
    if rng <= 0 or body <= 0:
        return None
    if side > 0 and lower >= wick_min * body and upper <= body:
        return "HAMMER"
    if side < 0 and upper >= wick_min * body and lower <= body:
        return "SHOOTING_STAR"
    if prev is not None:
        if side > 0 and prev.close < prev.open and b.close > b.open \
                and b.open <= prev.close and b.close >= prev.open:
            return "BULL_ENGULFING"
        if side < 0 and prev.close > prev.open and b.close < b.open \
                and b.open >= prev.close and b.close <= prev.open:
            return "BEAR_ENGULFING"
    return None


def zones(high: Sequence[float], low: Sequence[float], *, lookback: int = SR["lookback_sessions"],
          w: int = SR["pivot_half_width"], tol: float = SR["cluster_tol"],
          min_touches: int = SR["min_touches"],
          min_span: int = SR["min_span_sessions"]) -> list[float]:
    """Zone prices from the last `lookback` daily bars (oldest first, all before T)."""
    h, lo = list(high)[-lookback:], list(low)[-lookback:]
    n = len(h)
    piv: list[tuple[float, int]] = []
    for i in range(w, n - w):
        if h[i] == max(h[i - w:i + w + 1]):
            piv.append((h[i], i))
        if lo[i] == min(lo[i - w:i + w + 1]):
            piv.append((lo[i], i))
    piv.sort()
    out: list[float] = []
    group: list[tuple[float, int]] = []

    def close_group() -> None:
        if len(group) >= min_touches:
            idx = [i for _, i in group]
            if max(idx) - min(idx) >= min_span:
                out.append(sum(p for p, _ in group) / len(group))

    for p, i in piv:
        if group and p > group[0][0] * (1 + tol):
            close_group()
            group = []
        group.append((p, i))
    if group:
        close_group()
    return out


def blocked(entry: float, target: float, zs: Sequence[float]) -> float | None:
    """The first zone strictly between entry and target (the path to the target), or None."""
    lo, hi = min(entry, target), max(entry, target)
    inside = [z for z in zs if lo < z < hi]
    if not inside:
        return None
    return min(inside) if target > entry else max(inside)


def near(price: float, zs: Sequence[float], pct: float = SR["near_pct"]) -> float | None:
    best = None
    for z in zs:
        if abs(price - z) / price <= pct and (best is None or abs(price - z) < abs(price - best)):
            best = z
    return best
