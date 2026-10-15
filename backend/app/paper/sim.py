"""Stage 7 step 1: the paper MIS session simulator. PURE: no database, no network, no
broker, no clock. Design: docs/STAGE7_8_PAPER_DESIGN.md (decisions P1-P9, 2026-10-15).

One session, MIS: every target is bought by a market order at the official open and
squared off at the official close (nothing is held overnight).

  buy fill   open x (1 + (half_spread + slippage) / 1e4)
  sell fill  close x (1 - (half_spread + slippage) / 1e4)
  quantity   floor(order value / buy fill), capped at participation x prev-session volume
  no fill    locked day (high == low), no open or no close, quantity 0 (reason recorded)
  charges    e2.order_cost_parts with the dated MIS rates, per executed order (brokerage,
             statutory); spread and slippage are inside the fill prices, never charged twice

P&L identity (tested): end cash - start cash = sum(sell value - buy value) - sum(charges).
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from typing import Any

from app.training import e2 as X
from app.training import e4 as E4

MODE = "PAPER"


@dataclass(frozen=True)
class Config:
    capital_inr: float = 1_000_000.0
    order_value_inr: float = 100_000.0       # K = 10 at Rs 10 L (E4 D3)
    half_spread_bps: float = 5.0
    slippage_bps: float = 0.0
    participation: float = 0.01              # of the previous session's volume
    rates: X.Rates = E4.MIS


@dataclass(frozen=True)
class Bar:
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    prev_volume: float | None                # volume of the previous session (knowable at 09:15)


@dataclass
class Fill:
    key: str
    status: str                              # FILLED | PARTIAL | NOT_FILLED
    reason: str | None
    qty: int = 0
    buy_px: float | None = None
    sell_px: float | None = None
    buy_value: float = 0.0
    sell_value: float = 0.0
    charges: dict[str, float] = field(default_factory=dict)
    pnl_inr: float = 0.0
    mode: str = MODE


def _ok(x: float | None) -> bool:
    return x is not None and math.isfinite(x) and x > 0


def fill_one(key: str, bar: Bar | None, cfg: Config) -> Fill:
    if bar is None or not (_ok(bar.open) and _ok(bar.close)):
        return Fill(key, "NOT_FILLED", "no_open_or_close")
    if not (_ok(bar.high) and _ok(bar.low)) or bar.high == bar.low:
        return Fill(key, "NOT_FILLED", "locked_day")
    adj = (cfg.half_spread_bps + cfg.slippage_bps) / 10_000
    buy_px, sell_px = bar.open * (1 + adj), bar.close * (1 - adj)
    want = math.floor(cfg.order_value_inr / buy_px)
    cap = math.floor(cfg.participation * bar.prev_volume) if _ok(bar.prev_volume) else 0
    qty = min(want, cap)
    if qty <= 0:
        return Fill(key, "NOT_FILLED", "zero_quantity" if want <= 0 else "participation_cap")
    bv, sv = qty * buy_px, qty * sell_px
    b, s = X.order_cost_parts(bv, "BUY", cfg.rates), X.order_cost_parts(sv, "SELL", cfg.rates)
    charges = {p: b[p] + s[p] for p in b}
    return Fill(key, "FILLED" if qty == want else "PARTIAL",
                None if qty == want else "participation_cap", qty, buy_px, sell_px, bv, sv,
                charges, sv - bv - sum(charges.values()))


def simulate(targets: list[str], bars: dict[str, Bar], cfg: Config | None = None,
             start_cash: float | None = None) -> dict[str, Any]:
    """One MIS session. Targets are unique keys in priority order; orders that do not fit
    the cash are NOT_FILLED (insufficient_cash)."""
    cfg = cfg or Config()
    if len(set(targets)) != len(targets):
        raise ValueError("duplicate targets")
    cash = cfg.capital_inr if start_cash is None else start_cash
    start, fills, avail = cash, [], cash
    for k in targets:
        f = fill_one(k, bars.get(k), cfg)
        if f.qty and f.buy_value + f.charges.get("brokerage", 0) > avail:
            f = Fill(k, "NOT_FILLED", "insufficient_cash")
        avail -= f.buy_value
        fills.append(f)
    for f in fills:
        cash += f.sell_value - f.buy_value - sum(f.charges.values())
    filled = [f for f in fills if f.qty]
    out = {"mode": MODE, "targets": len(targets), "filled": len(filled),
           "not_filled": {r: sum(1 for f in fills if f.reason == r) for r in
                          sorted({f.reason for f in fills if f.reason})},
           "start_cash": start, "end_cash": cash, "pnl_inr": cash - start,
           "return": (cash - start) / start if start else None,
           "charges_inr": sum(sum(f.charges.values()) for f in fills),
           "turnover_inr": sum(f.buy_value + f.sell_value for f in fills),
           "fills": [asdict(f) for f in fills]}
    out["sha256"] = digest(targets, bars, cfg)
    return out


def digest(targets: list[str], bars: dict[str, Bar], cfg: Config) -> str:
    """sha256 of the inputs (P7): the same inputs always give the same sha."""
    body = {"targets": targets, "bars": {k: asdict(v) for k, v in sorted(bars.items())},
            "cfg": {**asdict(cfg), "rates": asdict(cfg.rates)}}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()
