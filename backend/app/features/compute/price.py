"""Price & technical features (diagram group 1). Daily bars, oldest first.

Definitions (parameters PROPOSED unless the diagram names them; decision
FEATURE-PARAMS):
  ret_n            close[-1] / close[-1-n] - 1                (1, 5, 20: SPECIFIED)
  sma_n            mean of the last n closes; close_to_sma_n = close / sma - 1
  ema_n            alpha = 2/(n+1), seeded with the SMA of the first n closes
  rsi_14           Wilder: seed = mean gain/loss of the first 14 changes,
                   then avg = (prev * 13 + x) / 14; RSI = 100 - 100/(1+RS)
  macd 12/26/9     line = ema12 - ema26 (from the 26th close); trigger = ema9
                   of the line; histogram = line - trigger
  atr_14           Wilder over the true range (needs a previous close)
  vol_20           sample stdev of the last 20 daily log returns * sqrt(252)
  beta_60          cov / var of the last 60 daily returns on dates common to
                   the stock and NIFTY 50
  range_20         close / max(high of the last 20) - 1, close / min(low) - 1
  breakout_20      1 if close > max(high of the 20 bars BEFORE the last), else 0
                   (breakdown: close < min(low) of those 20)
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from itertools import pairwise

from app.features.compute import (
    DIVISION_UNDEFINED,
    INSUFFICIENT_HISTORY,
    Bar,
    Result,
    miss,
    ok,
)


def _closes(bars: Sequence[Bar]) -> list[float]:
    return [b.close for b in bars]


def ret(bars: Sequence[Bar], n: int) -> Result:
    if len(bars) < n + 1:
        return miss(INSUFFICIENT_HISTORY)
    base = bars[-1 - n].close
    if base <= 0:
        return miss(DIVISION_UNDEFINED)
    return ok(bars[-1].close / base - 1)


def sma(bars: Sequence[Bar], n: int) -> Result:
    if len(bars) < n:
        return miss(INSUFFICIENT_HISTORY)
    return ok(sum(b.close for b in bars[-n:]) / n)


def close_to_sma(bars: Sequence[Bar], n: int) -> Result:
    s, why = sma(bars, n)
    if s is None:
        return (None, why)
    if s <= 0:
        return miss(DIVISION_UNDEFINED)
    return ok(bars[-1].close / s - 1)


def ema_series(values: Sequence[float], n: int) -> list[float]:
    """EMA seeded with the SMA of the first n values; one value per input from index n-1."""
    if len(values) < n:
        return []
    alpha = 2 / (n + 1)
    e = sum(values[:n]) / n
    out = [e]
    for v in values[n:]:
        e = alpha * v + (1 - alpha) * e
        out.append(e)
    return out


def ema(bars: Sequence[Bar], n: int) -> Result:
    s = ema_series(_closes(bars), n)
    return ok(s[-1]) if s else miss(INSUFFICIENT_HISTORY)


def rsi(bars: Sequence[Bar], n: int = 14) -> Result:
    c = _closes(bars)
    if len(c) < n + 1:
        return miss(INSUFFICIENT_HISTORY)
    ch = [b - a for a, b in pairwise(c)]
    gain = sum(max(x, 0.0) for x in ch[:n]) / n
    loss = sum(max(-x, 0.0) for x in ch[:n]) / n
    for x in ch[n:]:
        gain = (gain * (n - 1) + max(x, 0.0)) / n
        loss = (loss * (n - 1) + max(-x, 0.0)) / n
    if loss == 0:
        return ok(100.0) if gain > 0 else miss(DIVISION_UNDEFINED)
    return ok(100 - 100 / (1 + gain / loss))


def macd(bars: Sequence[Bar], fast: int = 12, slow: int = 26,
         trig: int = 9) -> tuple[Result, Result, Result]:
    c = _closes(bars)
    ef, es = ema_series(c, fast), ema_series(c, slow)
    if not es:
        return (miss(INSUFFICIENT_HISTORY),) * 3
    # align: es[i] corresponds to c[slow-1+i]; ef[j] to c[fast-1+j]
    line = [ef[(slow - fast) + i] - es[i] for i in range(len(es))]
    t = ema_series(line, trig)
    if not t:
        return ok(line[-1]), miss(INSUFFICIENT_HISTORY), miss(INSUFFICIENT_HISTORY)
    lv, tv = ok(line[-1]), ok(t[-1])
    # the histogram is the difference of the two NORMALISED values, so it is
    # exactly 0 when they agree (no floating-point residue such as 1e-15)
    return lv, tv, ok(lv[0] - tv[0])


def atr(bars: Sequence[Bar], n: int = 14) -> Result:
    if len(bars) < n + 1:
        return miss(INSUFFICIENT_HISTORY)
    tr = [max(b.high - b.low, abs(b.high - a.close), abs(b.low - a.close))
          for a, b in pairwise(bars)]
    a = sum(tr[:n]) / n
    for x in tr[n:]:
        a = (a * (n - 1) + x) / n
    return ok(a)


def atr_pct(bars: Sequence[Bar], n: int = 14) -> Result:
    a, why = atr(bars, n)
    if a is None:
        return (None, why)
    return ok(a / bars[-1].close) if bars[-1].close > 0 else miss(DIVISION_UNDEFINED)


def _log_returns(bars: Sequence[Bar]) -> list[float]:
    out = []
    for a, b in pairwise(bars):
        if a.close <= 0 or b.close <= 0:
            return []
        out.append(math.log(b.close / a.close))
    return out


def realised_vol(bars: Sequence[Bar], n: int = 20) -> Result:
    if len(bars) < n + 1:
        return miss(INSUFFICIENT_HISTORY)
    r = _log_returns(bars[-(n + 1):])
    if len(r) < n:
        return miss(DIVISION_UNDEFINED)
    m = sum(r) / n
    var = sum((x - m) ** 2 for x in r) / (n - 1)
    return ok(math.sqrt(var) * math.sqrt(252))


def beta(stock: Sequence[Bar], index: Sequence[Bar], n: int = 60) -> Result:
    def rets(bars: Sequence[Bar]) -> dict:
        return {b.day: b.close / a.close - 1 for a, b in pairwise(bars)
                if a.close > 0}
    rs, ri = rets(stock), rets(index)
    days = sorted(set(rs) & set(ri))[-n:]
    if len(days) < n:
        return miss(INSUFFICIENT_HISTORY)
    xs, ys = [ri[d] for d in days], [rs[d] for d in days]
    mx, my = sum(xs) / n, sum(ys) / n
    var = sum((x - mx) ** 2 for x in xs)
    if var == 0:
        return miss(DIVISION_UNDEFINED)
    return ok(sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / var)


def range_position(bars: Sequence[Bar], n: int = 20) -> tuple[Result, Result]:
    if len(bars) < n:
        return miss(INSUFFICIENT_HISTORY), miss(INSUFFICIENT_HISTORY)
    w = bars[-n:]
    hi, lo, c = max(b.high for b in w), min(b.low for b in w), bars[-1].close
    return (ok(c / hi - 1) if hi > 0 else miss(DIVISION_UNDEFINED),
            ok(c / lo - 1) if lo > 0 else miss(DIVISION_UNDEFINED))


def breakout(bars: Sequence[Bar], n: int = 20) -> tuple[Result, Result]:
    if len(bars) < n + 1:
        return miss(INSUFFICIENT_HISTORY), miss(INSUFFICIENT_HISTORY)
    prior = bars[-(n + 1):-1]
    c = bars[-1].close
    return (ok(1.0 if c > max(b.high for b in prior) else 0.0),
            ok(1.0 if c < min(b.low for b in prior) else 0.0))
