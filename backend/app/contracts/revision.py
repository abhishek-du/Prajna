"""Classify a later vendor observation of an already stored bar (phase 6). Pure.

The first observation is immutable (D3). A later, different observation is
never written over it; it is recorded in ohlcv_observation with one class:

  CA_ADJUSTMENT    explained exactly by recorded split/bonus events with
                   bar date < ex_date <= fetch date: every price equals
                   half-even(stored / F, tick), volume equals stored * F, open
                   interest unchanged (the key, i.e. the timestamp, is the same)
  ROUNDING         every price within one tick, volume and OI identical
  SETTLEMENT       the session's last bar only: open/high/low identical, close
                   and volume adjusted after the close (the known 15:52-16:02 IST
                   post-close adjustment)
  GLOBAL_REVISION  a global index/indicator label changed (their daily bars are
                   provisional by contract; phase 5 finality rules decide)
  UNEXPLAINED      anything else: fails closed (D3 is not weakened)

No instrument is special-cased: CHAVDA is simply the first real CA_ADJUSTMENT.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from decimal import Decimal
from itertools import combinations
from typing import Any

from app.contracts.ca_factor import adjust_price

PRICES = ("open", "high", "low", "close")
CLASSES = ("CA_ADJUSTMENT", "ROUNDING", "SETTLEMENT", "GLOBAL_REVISION", "UNEXPLAINED",
           "REOBSERVED")        # REOBSERVED: an identical later global observation
METHOD_VERSION = "revision-v1"


@dataclass(frozen=True, slots=True)
class Event:
    ca_id: int
    ex_date: _dt.date
    factor: Decimal


@dataclass(frozen=True, slots=True)
class Verdict:
    classification: str
    reason: str
    explained_by: dict[str, Any]

    @property
    def fails(self) -> bool:
        return self.classification == "UNEXPLAINED"


def _d(v) -> Decimal | None:
    return None if v is None else Decimal(str(v))


def classify(stored: dict, new: dict, *, bar_date: _dt.date, fetch_date: _dt.date,
             tick: Decimal | None, events: list[Event], is_global: bool = False,
             last_bar_of_session: bool = False) -> Verdict:
    s = {k: _d(stored.get(k)) for k in (*PRICES, "volume", "open_interest")}
    n = {k: _d(new.get(k)) for k in (*PRICES, "volume", "open_interest")}
    if is_global:
        return Verdict("GLOBAL_REVISION", "global daily label changed after first observation",
                       {"stored": {k: str(v) for k, v in s.items()}})
    if s["open_interest"] != n["open_interest"]:
        return Verdict("UNEXPLAINED", "open interest changed", {})
    applicable = sorted((e for e in events if bar_date < e.ex_date <= fetch_date),
                        key=lambda e: e.ex_date)
    if tick:
        # every non-empty subset of the applicable events, largest first
        for k in range(len(applicable), 0, -1):
            for combo in combinations(applicable, k):
                f = Decimal(1)
                for e in combo:
                    f *= e.factor
                if f == 1:
                    continue
                prices_ok = all(adjust_price(s[p], f, tick) == n[p] for p in PRICES)
                vol_ok = s["volume"] is not None and n["volume"] == (s["volume"] * f)
                if prices_ok and vol_ok:
                    return Verdict("CA_ADJUSTMENT", f"explained by factor {f}",
                                   {"factor": str(f), "ca_ids": [e.ca_id for e in combo],
                                    "ex_dates": [str(e.ex_date) for e in combo],
                                    "tick": str(tick), "rounding": "half-even"})
        if all(abs(s[p] - n[p]) <= tick for p in PRICES) and s["volume"] == n["volume"]:
            return Verdict("ROUNDING", "prices within one tick", {"tick": str(tick)})
    if last_bar_of_session and all(s[p] == n[p] for p in ("open", "high", "low")) \
            and n["volume"] >= s["volume"]:
        return Verdict("SETTLEMENT", "last bar of the session adjusted after the close", {})
    return Verdict("UNEXPLAINED", "no rule explains the difference",
                   {"applicable_events": [e.ca_id for e in applicable]})
