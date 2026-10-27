"""The intraday Buy List (user 2026-10-27): before the open, every stock the rules
(dash-plan-v2) or the Research Desk (LLM) call BUY, with how far it typically moves in a day
(ATR), its entry, stop and targets; at the end of the day each pick is graded on its 1-minute
path as an intraday trade (buy at the 09:15 open; the first of the stop or T1, else out at
15:15; MIS costs and spread). PAPER research: never advice, never an order."""

from __future__ import annotations

import datetime as _dt
import math
from typing import Any

from app.lab.forensic import Bar

TOP = 40
# intraday levels in daily ATRs from the 09:15 open (a normal day moves ~1 ATR): the stop
# outside the opening noise, T1 at 1.5 R (doctrine 2: RRR >= 1.5), T2 at the typical high
STOP_ATR, T1_ATR, T2_ATR = 0.5, 0.75, 1.0
COST = 0.0018 + 0.001          # MIS round trip at Rs 1 L (~0.18 %) + 5 bps spread a side
NOTIONAL = 100_000.0
EXIT_BY = _dt.time(15, 15)


def _f(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _p(a: float | None, b: float | None) -> float | None:
    return None if a is None or not b else a / b - 1


def intraday_levels(anchor: float, atr_pct: float | None) -> dict[str, float | None]:
    if not anchor or not atr_pct:
        return {"stop": None, "t1": None, "t2": None}
    return {"stop": anchor * (1 - STOP_ATR * atr_pct), "t1": anchor * (1 + T1_ATR * atr_pct),
            "t2": anchor * (1 + T2_ATR * atr_pct)}


def item(key: str, meta: dict[str, Any], px: dict[str, Any], rule: dict[str, Any],
         desk: dict[str, Any] | None) -> dict[str, Any] | None:
    """One Buy List row, or None when neither the rules nor the desk say BUY. Levels: the
    desk's when it says BUY (the LLM decides), else the rule plan's."""
    c, atrp = _f(px.get("close")), _f(px.get("atr_pct"))
    if not c:
        return None
    d_buy = bool(desk and desk.get("decision") in ("BUY", "STRONG_BUY"))
    r_buy = rule.get("decision") == "BUY"
    if not (d_buy or r_buy):
        return None
    pl = rule.get("plan") or {}
    if d_buy:
        lo, hi, sl, t1, t2 = (_f(desk.get(k)) for k in ("entry_lo", "entry_hi", "stop", "t1", "t2"))
        src = "DESK"
    else:
        ez = pl.get("entry_zone") or [None, None]
        lo, hi, sl, t1, t2 = _f(ez[0]), _f(ez[1]), _f(pl.get("stop_loss")), _f(pl.get("t1")), \
            _f(pl.get("t2"))
        src = "RULES"
    swing = {"entry_lo": lo, "entry_hi": hi, "stop": sl, "t1": t1, "t2": t2}
    il = intraday_levels(c, atrp)          # shown from the previous close; re-anchored at 09:15
    lo, hi, sl, t1, t2 = c * (1 - 0.25 * (atrp or 0)), c * (1 + 0.25 * (atrp or 0)), \
        il["stop"], il["t1"], il["t2"]
    rs = _f((rule.get("signal") or {}).get("score")) or 0.0
    ds = _f((desk or {}).get("score"))
    rank = (ds if ds is not None else 0.0) + 10 * rs + (50 if d_buy and r_buy else 0)
    return {
        "key": key, "symbol": meta.get("symbol"), "sector": meta.get("sector"),
        "prev_close": c, "atr_pct": atrp,
        "typical_high": c * (1 + atrp) if atrp else None,         # ~1 ATR: a normal day's range
        "typical_up_pct": atrp, "half_atr_pct": atrp / 2 if atrp else None,
        "entry_lo": lo, "entry_hi": hi, "stop": sl, "t1": t1, "t2": t2,
        "t1_pct": _p(t1, c), "t2_pct": _p(t2, c), "stop_pct": _p(sl, c),
        "rr_t1": (t1 - c) / (c - sl) if t1 and sl and c > sl else None,
        "levels_basis": f"intraday: from the 09:15 open, stop -{STOP_ATR:g} ATR, T1 +{T1_ATR:g} "
                        f"ATR (1.5 R), T2 +{T2_ATR:g} ATR (typical day high)",
        "swing_plan": swing, "levels_from": src, "rule_decision": rule.get("decision"),
        "rule_score": rs,
        "rule_flags": rule.get("flags") or [], "desk_decision": (desk or {}).get("decision"),
        "desk_score": ds, "desk_why": ((desk or {}).get("why_moved") or {}).get("summary"),
        "desk_thesis": (desk or {}).get("thesis"), "agree": d_buy and r_buy, "rank": rank,
        "rsi_14": _f(px.get("rsi_14")), "ret_1d": _f(px.get("ret_1d")),
        "ret_5d": _f(px.get("ret_5d"))}


def rank_items(rows: list[dict[str, Any]], top: int = TOP) -> list[dict[str, Any]]:
    return sorted((r for r in rows if r), key=lambda r: -r["rank"])[:top]


def grade_one(it: dict[str, Any], bars: list[Bar], day: _dt.date) -> dict[str, Any]:
    """The pick as an intraday trade on its 1-minute path (pure). Buy at the first bar's
    open; exit at the first touch of the stop (first when both touch in one bar) or T1,
    else at the last close at or before 15:15 IST."""
    from app.core.clock import IST
    out = {"symbol": it.get("symbol"), "key": it.get("key"), "levels_from": it.get("levels_from"),
           "agree": it.get("agree")}
    if not bars:
        return {**out, "status": "NO_DATA"}
    entry = _f(bars[0].open) or bars[0].close
    il = intraday_levels(entry, _f(it.get("atr_pct")))       # re-anchored at the real open
    sl, t1 = il["stop"], il["t1"]
    hi, lo = max(b.high for b in bars), min(b.low for b in bars)
    exit_px, why, at = None, "EOD", None
    for b in bars:
        if b.start.astimezone(IST).time() >= EXIT_BY:
            break
        if sl and b.low <= sl:
            exit_px, why, at = min(sl, b.high), "STOP", b.end
            break
        if t1 and b.high >= t1:
            exit_px, why, at = max(t1, b.low), "T1", b.end
            break
        exit_px, at = b.close, b.end
    if exit_px is None:
        exit_px = bars[-1].close
    gross = exit_px / entry - 1
    net = gross - COST
    return {**out, "status": why, "entry": entry, "exit": exit_px, "exit_at": at,
            "stop": sl, "t1": t1, "t2": il["t2"],
            "gross_pct": gross, "net_pct": net, "net_inr": net * NOTIONAL,
            "open_to_high_pct": hi / entry - 1, "open_to_low_pct": lo / entry - 1,
            "open_to_close_pct": bars[-1].close / entry - 1,
            "reached_typical_high": bool(it.get("typical_high") and hi >= it["typical_high"]),
            "prev_close": it.get("prev_close"), "gap_pct": _p(entry, _f(it.get("prev_close")))}


def summary(grades: list[dict[str, Any]]) -> dict[str, Any]:
    g = [x for x in grades if x.get("status") not in (None, "NO_DATA")]
    if not g:
        return {"picks": len(grades), "graded": 0}
    nets = [x["net_pct"] for x in g]
    return {"picks": len(grades), "graded": len(g),
            "profitable": sum(1 for x in nets if x > 0),
            "t1_hit": sum(x["status"] == "T1" for x in g),
            "stopped": sum(x["status"] == "STOP" for x in g),
            "eod": sum(x["status"] == "EOD" for x in g),
            "avg_net_pct": sum(nets) / len(nets), "total_net_inr": sum(x["net_inr"] for x in g),
            "best": max(g, key=lambda x: x["net_pct"])["symbol"],
            "worst": min(g, key=lambda x: x["net_pct"])["symbol"],
            "agree_avg_net_pct": (sum(x["net_pct"] for x in g if x.get("agree"))
                                  / max(1, sum(1 for x in g if x.get("agree"))))
            if any(x.get("agree") for x in g) else None}
