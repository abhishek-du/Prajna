"""Live indicators for the dashboard (user 2026-10-22): the Stage 3 price definitions
(app.features.compute.price, the same functions) on the stored daily bars up to the last
session plus TODAY's bar built from the live quote (open, high, low, last price, volume).

DISPLAY ONLY, never stored and never a model or feature input. The history is the stored
canonical daily bars (vendor adjusted, as stored), not pit.bars_adjusted per stock (too
slow for 3,500 names every 30 s). A stock with a corporate action in the window can
therefore differ a little from its Stage 3 value. The page labels these values "live".
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.compute import Bar
from app.features.compute import price as PR

HISTORY = 300                       # sessions kept per stock (SMA 200, 252-day range, ...)
LIVE_IDS = ("ret_1d", "ret_5d", "ret_20d", "close_to_sma_20", "close_to_sma_50",
            "close_to_sma_200", "rsi_14", "macd_histogram", "atr_pct_14", "volatility_20",
            "dist_high_252", "dist_low_252")


async def load_history(s: AsyncSession, before: _dt.date) -> dict[str, list[Bar]]:
    """The last HISTORY stored daily bars before `before`, per NSE instrument, oldest first."""
    rows = (await s.execute(text("""
        select instrument_key, market_date, open, high, low, close, volume from (
          select instrument_key, market_date, open, high, low, close, volume,
                 row_number() over (partition by instrument_key order by market_date desc) rn
          from canon_market_bar where timeframe = '1d' and segment in ('NSE_EQ', 'NSE_INDEX')
            and market_date < :d and market_date > :d0) x
        where rn <= :n order by instrument_key, market_date"""),
        {"d": before, "d0": before - _dt.timedelta(days=HISTORY * 2), "n": HISTORY})).all()
    out: dict[str, list[Bar]] = {}
    for k, d, o, h, lo, c, v in rows:
        if None in (o, h, lo, c):
            continue
        out.setdefault(k, []).append(Bar(d, float(o), float(h), float(lo), float(c),
                                         float(v or 0)))
    return out


def compute(hist: list[Bar], q: dict[str, Any]) -> dict[str, float | None]:
    """Stage 3's price features with today's live bar appended."""
    ltp = q.get("ltp")
    if not ltp or not hist:
        return {}
    o = q.get("open") or ltp
    h = max(x for x in (q.get("high"), ltp, o) if x is not None)
    lo = min(x for x in (q.get("low"), ltp, o) if x is not None)
    today = _dt.date.fromisoformat(q["date"])
    bars = [b for b in hist if b.day < today]
    bars.append(Bar(today, float(o), float(h), float(lo), float(ltp), float(q.get("volume") or 0)))

    def v(res):
        return res[0]
    out: dict[str, float | None] = {
        "ret_1d": v(PR.ret(bars, 1)), "ret_5d": v(PR.ret(bars, 5)),
        "ret_20d": v(PR.ret(bars, 20)),
        "close_to_sma_20": v(PR.close_to_sma(bars, 20)),
        "close_to_sma_50": v(PR.close_to_sma(bars, 50)),
        "close_to_sma_200": v(PR.close_to_sma(bars, 200)),
        "rsi_14": v(PR.rsi(bars, 14)), "atr_pct_14": v(PR.atr_pct(bars, 14)),
        "volatility_20": v(PR.realised_vol(bars, 20))}
    out["macd_histogram"] = v(PR.macd(bars)[2])
    hi, lw = PR.range_position(bars, 252)
    out["dist_high_252"], out["dist_low_252"] = v(hi), v(lw)
    return out


def compute_all(history: dict[str, list[Bar]], quotes: dict[str, dict[str, Any]]
                ) -> dict[str, dict[str, float | None]]:
    return {k: f for k, q in quotes.items() if (f := compute(history.get(k, []), q))}
