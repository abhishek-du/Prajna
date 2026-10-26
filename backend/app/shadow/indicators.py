"""Textbook indicators (Varsity M2), pure: lists in, lists out, None until warm.
Wilder smoothing for ATR, ADX and RSI; EMA seeded with the SMA of its first n values."""

from __future__ import annotations

import math
from collections.abc import Sequence

Num = float | None


def sma(x: Sequence[float], n: int) -> list[Num]:
    out: list[Num] = [None] * len(x)
    s = 0.0
    for i, v in enumerate(x):
        s += v
        if i >= n:
            s -= x[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def ema(x: Sequence[float], n: int) -> list[Num]:
    out: list[Num] = [None] * len(x)
    if len(x) < n:
        return out
    a = 2.0 / (n + 1)
    e = sum(x[:n]) / n
    out[n - 1] = e
    for i in range(n, len(x)):
        e = a * x[i] + (1 - a) * e
        out[i] = e
    return out


def stdev(x: Sequence[float], n: int) -> list[Num]:
    """Population standard deviation over n (the Bollinger convention)."""
    out: list[Num] = [None] * len(x)
    for i in range(n - 1, len(x)):
        w = x[i - n + 1:i + 1]
        m = sum(w) / n
        out[i] = math.sqrt(sum((v - m) ** 2 for v in w) / n)
    return out


def bollinger(x: Sequence[float], n: int = 20, k: float = 2.0
              ) -> tuple[list[Num], list[Num], list[Num]]:
    mid, sd = sma(x, n), stdev(x, n)
    lo = [None if m is None else m - k * s for m, s in zip(mid, sd)]
    hi = [None if m is None else m + k * s for m, s in zip(mid, sd)]
    return lo, mid, hi


def true_range(h: Sequence[float], lo: Sequence[float], c: Sequence[float]) -> list[float]:
    return [h[0] - lo[0]] + [max(h[i] - lo[i], abs(h[i] - c[i - 1]), abs(lo[i] - c[i - 1]))
                             for i in range(1, len(c))]


def _wilder(x: Sequence[float], n: int, start: int = 0) -> list[Num]:
    """Wilder's smoothing of x[start:], seeded with the mean of its first n values."""
    out: list[Num] = [None] * len(x)
    if len(x) - start < n:
        return out
    v = sum(x[start:start + n]) / n
    out[start + n - 1] = v
    for i in range(start + n, len(x)):
        v = (v * (n - 1) + x[i]) / n
        out[i] = v
    return out


def atr(h: Sequence[float], lo: Sequence[float], c: Sequence[float], n: int = 14) -> list[Num]:
    return _wilder(true_range(h, lo, c), n)


def rsi(c: Sequence[float], n: int = 14) -> list[Num]:
    out: list[Num] = [None] * len(c)
    if len(c) <= n:
        return out
    gains = [0.0] + [max(c[i] - c[i - 1], 0.0) for i in range(1, len(c))]
    losses = [0.0] + [max(c[i - 1] - c[i], 0.0) for i in range(1, len(c))]
    g, lo = _wilder(gains, n, 1), _wilder(losses, n, 1)
    for i in range(len(c)):
        if g[i] is None:
            continue
        out[i] = 100.0 if lo[i] == 0 else 100.0 - 100.0 / (1.0 + g[i] / lo[i])
    return out


def adx(h: Sequence[float], lo: Sequence[float], c: Sequence[float], n: int = 14) -> list[Num]:
    """Wilder ADX: +DM/-DM and TR smoothed over n, DX = |+DI - -DI| / (+DI + -DI), ADX = the
    Wilder mean of DX (first value at index 2n - 1)."""
    m = len(c)
    out: list[Num] = [None] * m
    if m < 2 * n:
        return out
    pdm, ndm = [0.0], [0.0]
    for i in range(1, m):
        up, dn = h[i] - h[i - 1], lo[i - 1] - lo[i]
        pdm.append(up if up > dn and up > 0 else 0.0)
        ndm.append(dn if dn > up and dn > 0 else 0.0)
    tr = true_range(h, lo, c)
    s_tr, s_p, s_n = _wilder(tr, n, 1), _wilder(pdm, n, 1), _wilder(ndm, n, 1)
    dx: list[float] = []
    first = None
    for i in range(m):
        if s_tr[i] is None:
            continue
        if first is None:
            first = i
        pdi = 100 * s_p[i] / s_tr[i] if s_tr[i] else 0.0
        ndi = 100 * s_n[i] / s_tr[i] if s_tr[i] else 0.0
        dx.append(0.0 if pdi + ndi == 0 else 100 * abs(pdi - ndi) / (pdi + ndi))
    a = _wilder(dx, n)
    for j, v in enumerate(a):
        out[first + j] = v
    return out


def vwap(h: Sequence[float], lo: Sequence[float], c: Sequence[float],
         v: Sequence[float]) -> list[Num]:
    """Cumulative session VWAP on the typical price (H + L + C) / 3; None until volume."""
    out: list[Num] = []
    pv = vol = 0.0
    for i in range(len(c)):
        pv += (h[i] + lo[i] + c[i]) / 3.0 * v[i]
        vol += v[i]
        out.append(pv / vol if vol > 0 else None)
    return out
