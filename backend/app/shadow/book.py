"""The L0 guards on a strategy's shadow book and the placebo (pre-registration §5, §6),
PURE. Candidates are taken in entry-time order (ties: the strategy's rank, then key):

  size        qty = floor(floor(risk / |entry - stop|) x size factor), capped by the
              notional cap and 1 % of the 20-session median daily volume
  caps        <= 3 open, open risk + new <= 3 % of equity, <= 3 open per known sector
  daily halt  realised + open mark-to-market <= -3 % at a new entry -> HALT_DAILY for the
              rest of the session (open trades keep their stops)
  first stop  after the book's first STOP / STOP_GAP exit, no new entry (HALT_FIRST_STOP)
  drawdown    flags from the book's earlier sessions: >= 5 % DD_HALF, >= 10 % DD_HALT
              (recorded only in P1)
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import math
from typing import Any

import numpy as np

from app.shadow import fill as F
from app.shadow import indicators as I
from app.shadow.bars import NameDay
from app.shadow.spec import BOOK, POLICY_VERSION
from app.shadow.strategies import Candidate, Skip


def size(per_share: float, size_factor: float, entry: float,
         median_volume: float | None) -> int:
    if per_share <= 0:
        return 0
    risk = BOOK["equity_inr"] * BOOK["risk_pct"]
    q = math.floor(math.floor(risk / per_share) * size_factor)
    q = min(q, math.floor(BOOK["notional_cap_inr"] / entry))
    q = min(q, math.floor(BOOK["participation"] * median_volume) if median_volume else 0)
    return max(q, 0)


def dd_flags(prior_daily_net: list[float]) -> list[str]:
    cum = peak = 0.0
    for p in prior_daily_net:
        cum += p
        peak = max(peak, cum)
    dd = (peak - cum) / BOOK["equity_inr"]
    return [f for f, ok in (("DD_HALF", dd >= BOOK["dd_half"]),
                            ("DD_HALT", dd >= BOOK["dd_halt"])) if ok]


def trade_row(c: Candidate, nd: NameDay, qty: int, p: F.Path, *, placebo: bool,
              guard_flags: list[str], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    per = abs(c.entry_raw - c.stop)
    risk_inr = qty * per
    by_slip = {}
    for sl in BOOK["slippage_bps"]:
        st = F.settle(c.side, qty, c.entry_raw, p.exit_raw, sl)
        by_slip[str(int(sl))] = {"net_inr": st["net_inr"],
                                 "net_r": st["net_inr"] / risk_inr if risk_inr else None}
    st0 = F.settle(c.side, qty, c.entry_raw, p.exit_raw, BOOK["slippage_bps"][0])
    return {"strategy": c.strategy, "instrument_key": c.key, "side": c.side,
            "is_placebo": placebo, "signal_at": c.signal_at, "entry_at": c.entry_at,
            "exit_at": p.exit_at, "entry_raw": c.entry_raw, "stop": c.stop,
            "target": c.target, "atr": c.atr, "time_stop": c.time_stop,
            "time_reason": c.time_reason, "qty": qty, "size_factor": c.size_factor,
            "risk_inr": risk_inr, "rrr": c.rrr, "checklist": c.checklist,
            "checklist_score": c.score, "exit_raw": p.exit_raw, "exit_reason": p.reason,
            "entry_px": st0["entry_px"], "exit_px": st0["exit_px"],
            "gross_inr": st0["gross_inr"], "charges": st0["charges"],
            "net_inr": st0["net_inr"], "net_r": st0["net_inr"] / risk_inr if risk_inr else None,
            "by_slippage": by_slip, "sector": nd.sector, "guard_flags": guard_flags,
            "evidence": {**c.evidence, **(extra or {})}}


def run(cands: list[Candidate], names: dict[str, NameDay], *,
        prior_daily_net: list[float]) -> tuple[list[dict], list[Skip], list[str]]:
    flags = dd_flags(prior_daily_net)
    taken: list[dict] = []
    skips: list[Skip] = []
    halted = False
    order = sorted(cands, key=lambda c: (c.entry_at, tuple(-x for x in c.rank), c.key))
    for c in order:
        nd = names[c.key]
        t = c.entry_at
        is_open = [x for x in taken if x["entry_at"] <= t < x["exit_at"]]
        if not halted:
            realised = sum(x["net_inr"] for x in taken if x["exit_at"] <= t)
            mtm = 0.0
            for x in is_open:
                mk = F.mark(names[x["instrument_key"]].m1, t)
                if mk is not None:
                    mtm += x["side"] * x["qty"] * (mk - x["entry_raw"])
            if realised + mtm <= -BOOK["daily_loss_halt"] * BOOK["equity_inr"]:
                halted = True
        if halted:
            skips.append(Skip(c.strategy, c.key, "HALT_DAILY", c.signal_at))
            continue
        if BOOK["halt_after_first_stop"] and any(
                x["exit_reason"] in ("STOP", "STOP_GAP") and x["exit_at"] <= t for x in taken):
            skips.append(Skip(c.strategy, c.key, "HALT_FIRST_STOP", c.signal_at))
            continue
        qty = size(abs(c.entry_raw - c.stop), c.size_factor, c.entry_raw, nd.median_volume_20d)
        if qty <= 0:
            skips.append(Skip(c.strategy, c.key, "CAP_LIQUIDITY", c.signal_at,
                              {"median_volume_20d": nd.median_volume_20d}))
            continue
        new_risk = qty * abs(c.entry_raw - c.stop)
        if (len(is_open) >= min(BOOK["max_open"], BOOK["max_positions"])
                or sum(x["risk_inr"] for x in is_open) + new_risk
                > BOOK["open_risk_cap"] * BOOK["equity_inr"] + 1e-6):
            skips.append(Skip(c.strategy, c.key, "CAP_OPEN_RISK", c.signal_at,
                              {"open": len(is_open)}))
            continue
        if nd.sector and sum(1 for x in is_open if x["sector"] == nd.sector) >= BOOK["sector_cap"]:
            skips.append(Skip(c.strategy, c.key, "CAP_SECTOR", c.signal_at))
            continue
        p = F.path(nd.m1, c.side, c.entry_at, c.stop, c.target, c.time_stop, c.time_reason)
        if p is None:
            skips.append(Skip(c.strategy, c.key, "NO_INTRADAY_BARS", c.signal_at))
            continue
        taken.append(trade_row(c, nd, qty, p, placebo=False, guard_flags=list(flags)))
    return taken, skips, flags


def _seed(strategy: str, session: _dt.date, seq: int) -> int:
    h = hashlib.sha256(f"{strategy}|{POLICY_VERSION}|{session}|{seq}".encode()).hexdigest()
    return int(h[:16], 16)


def _atr_at(nd: NameDay, t: _dt.datetime, n: int = 14) -> float | None:
    a = I.atr([b.high for b in nd.m15], [b.low for b in nd.m15], [b.close for b in nd.m15], n)
    for b, v in zip(nd.m15, a):
        if b.end == t:
            return v
    return None


def placebo(taken: list[dict], names: dict[str, NameDay], pool: list[str],
            strategy: str, session: _dt.date, tries: int = 50) -> list[dict]:
    """For each taken trade (in order), the same entry time, side, stop/target distances
    in ATR units, time stop, size factor and size rule on a name drawn at random (seeded)
    from the eligible pool, excluding the real trades' names and earlier placebo names."""
    real = {x["instrument_key"] for x in taken}
    used: set[str] = set()
    out = []
    srt = sorted(pool)
    for seq, x in enumerate(sorted(taken, key=lambda r: (r["entry_at"], r["instrument_key"]))):
        rng = np.random.default_rng(_seed(strategy, session, seq))
        ks = x["atr"] and abs(x["entry_raw"] - x["stop"]) / x["atr"]
        kt = x["atr"] and abs(x["target"] - x["entry_raw"]) / x["atr"]
        for _ in range(tries):
            k = srt[int(rng.integers(len(srt)))] if srt else None
            if k is None:
                break
            if k in real or k in used:
                continue
            nd = names.get(k)
            if nd is None:
                continue
            eb = next((b for b in nd.m1 if b.start == x["entry_at"]), None)
            a = _atr_at(nd, x["signal_at"])
            if eb is None or not a:
                continue
            side, e = x["side"], eb.open
            c = Candidate(strategy, k, side, x["signal_at"], x["entry_at"], e,
                          e - side * ks * a, e + side * kt * a, a, x["time_stop"],
                          x["time_reason"], x["size_factor"], dict(x["checklist"]), (0,), {})
            qty = size(abs(e - c.stop), c.size_factor, e, nd.median_volume_20d)
            p = F.path(nd.m1, side, c.entry_at, c.stop, c.target, c.time_stop, c.time_reason)
            if qty <= 0 or p is None:
                continue
            used.add(k)
            out.append(trade_row(c, nd, qty, p, placebo=True, guard_flags=[],
                                 extra={"mirror_of": x["instrument_key"], "draw_seq": seq}))
            break
    return out
