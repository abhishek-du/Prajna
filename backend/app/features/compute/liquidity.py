"""Volume & liquidity features (diagram group 2). Daily bars, oldest first.

  avg_volume_20     mean volume of the last 20 sessions          (PROPOSED window)
  volume_spike_20   volume of the last session / mean volume of the 20 before it
  turnover_20       mean(close * volume) of the last 20 sessions (INR)
Bid-ask spread and all-day order-book imbalance: UNSUPPORTED (no live tick
store; Stage 7). The pre-open book imbalance is a pre-open feature.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.features.compute import DIVISION_UNDEFINED, INSUFFICIENT_HISTORY, Bar, Result, miss, ok


def avg_volume(bars: Sequence[Bar], n: int = 20) -> Result:
    if len(bars) < n:
        return miss(INSUFFICIENT_HISTORY)
    return ok(sum(b.volume for b in bars[-n:]) / n)


def volume_spike(bars: Sequence[Bar], n: int = 20) -> Result:
    if len(bars) < n + 1:
        return miss(INSUFFICIENT_HISTORY)
    base = sum(b.volume for b in bars[-(n + 1):-1]) / n
    return ok(bars[-1].volume / base) if base > 0 else miss(DIVISION_UNDEFINED)


def turnover(bars: Sequence[Bar], n: int = 20) -> Result:
    if len(bars) < n:
        return miss(INSUFFICIENT_HISTORY)
    return ok(sum(b.close * b.volume for b in bars[-n:]) / n)
