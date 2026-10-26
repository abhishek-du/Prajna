"""The 1m trade-path simulator (pre-registration §5), PURE.

The path depends on raw prices only: the stop and target are levels set from the raw
entry, so the exit bar and reason are the same at every slippage; the fills then apply
half-spread + slippage against the trade (entry and every exit).

  entry      the open of the entry bar
  each bar   from the entry bar on, in order:
               the open beyond the stop (not on the entry bar)  -> STOP_GAP at the open
               low <= stop (long) / high >= stop (short)        -> STOP at the stop
               high >= target (long) / low <= target (short)    -> TARGET at the target
             (one bar touching both: the stop first, pessimistic)
               the bar ending at the time stop                  -> its close
  charges    e2.order_cost_parts with the dated MIS rates, per order
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Any

from app.shadow.bars import IBar
from app.shadow.spec import BOOK
from app.training import e2 as X
from app.training import e4 as E4


@dataclass(frozen=True)
class Path:
    exit_at: _dt.datetime          # the end of the exit bar
    exit_raw: float
    reason: str                    # STOP | STOP_GAP | TARGET | TIME_NOT_WORKING | EOD | NO_EXIT_BAR


def path(m1: list[IBar], side: int, entry_at: _dt.datetime, stop: float, target: float,
         time_stop: _dt.datetime, time_reason: str) -> Path | None:
    bars = [b for b in m1 if b.start >= entry_at]
    if not bars or bars[0].start != entry_at:
        return None
    for j, b in enumerate(bars):
        if b.end > time_stop:
            break
        if side > 0:
            if j and b.open <= stop:
                return Path(b.end, b.open, "STOP_GAP")
            if b.low <= stop:
                return Path(b.end, stop, "STOP")
            if b.high >= target:
                return Path(b.end, target, "TARGET")
        else:
            if j and b.open >= stop:
                return Path(b.end, b.open, "STOP_GAP")
            if b.high >= stop:
                return Path(b.end, stop, "STOP")
            if b.low <= target:
                return Path(b.end, target, "TARGET")
        if b.end == time_stop:
            return Path(b.end, b.close, time_reason)
    last = [b for b in bars if b.end <= time_stop]
    if not last:
        return None
    return Path(last[-1].end, last[-1].close, "NO_EXIT_BAR")


def mark(m1: list[IBar], t: _dt.datetime) -> float | None:
    out = None
    for b in m1:
        if b.end <= t:
            out = b.close
        else:
            break
    return out


def settle(side: int, qty: int, entry_raw: float, exit_raw: float, slippage_bps: float,
           rates: X.Rates = E4.MIS) -> dict[str, Any]:
    adj = (BOOK["half_spread_bps"] + slippage_bps) / 10_000
    if side > 0:
        buy_px, sell_px = entry_raw * (1 + adj), exit_raw * (1 - adj)
    else:
        sell_px, buy_px = entry_raw * (1 - adj), exit_raw * (1 + adj)
    bv, sv = qty * buy_px, qty * sell_px
    b, s = X.order_cost_parts(bv, "BUY", rates), X.order_cost_parts(sv, "SELL", rates)
    charges = {p: b[p] + s[p] for p in b}
    gross = sv - bv
    return {"entry_px": buy_px if side > 0 else sell_px,
            "exit_px": sell_px if side > 0 else buy_px,
            "gross_inr": gross, "charges": charges, "net_inr": gross - sum(charges.values())}
