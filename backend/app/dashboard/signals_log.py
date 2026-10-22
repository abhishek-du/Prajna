"""Forward record of the dashboard's trade plans (user 2026-10-22: measure whether the
rules work). PAPER RESEARCH ONLY: nothing here places, modifies or cancels an order.

snapshot   every trading day at 16:45 IST (after NSE's official close), every BUY and
           SELL / AVOID plan of the day, written to var/dashboard/signals/<day>.jsonl with
           the day's close: a point-in-time record, never rewritten afterwards.
evaluate   from the stored daily bars of the sessions AFTER the plan's day (up to 10):

  BUY   filled on the first session whose low reaches the entry (at min(open, entry)).
        From the fill: a session touching the stop and a target is counted as the STOP
        (conservative). T1 first: half is booked at T1 and the stop moves to the entry; then
        T2 books the rest, or the entry stop ends it at 0. Still open after 10 sessions:
        marked at the last close. Result in R (risk = entry - stop); costs not included.
  SELL / AVOID   a view, not a trade: the 5-session return from the plan's close (it should
        be negative) and whether downside 1 was reached before the view's stop.
"""

from __future__ import annotations

import datetime as _dt
import json
import pathlib
from typing import Any

DIR = pathlib.Path(__file__).resolve().parents[2] / "var" / "dashboard" / "signals"
HORIZON = 10
VIEW_HORIZON = 5
FIELDS = ("key", "symbol", "sector", "cap_bucket", "action", "signal_score", "price",
          "entry_zone", "entry", "stop_loss", "t1", "t2", "buy_trigger", "exit_zone",
          "version")


def write(day: _dt.date, plans: list[dict[str, Any]], *, overwrite: bool = False) -> dict:
    DIR.mkdir(parents=True, exist_ok=True)
    p = DIR / f"{day.isoformat()}.jsonl"
    if p.exists() and not overwrite:
        return {"day": str(day), "written": 0, "exists": True}
    rows = [{**{k: x.get(k) for k in FIELDS}, "day": str(day)} for x in plans
            if x.get("action") in ("BUY", "SELL / AVOID")]
    tmp = p.with_suffix(".part")
    tmp.write_text("".join(json.dumps(r) + "\n" for r in rows))
    tmp.replace(p)
    return {"day": str(day), "written": len(rows), "exists": False}


def load(days: int = 60) -> list[dict[str, Any]]:
    if not DIR.exists():
        return []
    out = []
    for p in sorted(DIR.glob("*.jsonl"))[-days:]:
        out += [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
    return out


def _buy(r: dict[str, Any], bars: list[dict[str, Any]]) -> dict[str, Any]:
    e, sl, t1, t2 = r["entry"], r["stop_loss"], r["t1"], r["t2"]
    if None in (e, sl, t1, t2) or e <= sl:
        return {"status": "INVALID"}
    risk = e - sl
    fill = None
    half = False
    for b in bars[:HORIZON]:
        if fill is None:
            if b["low"] <= e:
                fill = min(b["open"], e)
                risk = fill - sl
                if risk <= 0:
                    return {"status": "GAP_BELOW_STOP", "filled_on": b["date"],
                            "r": (b["close"] - fill) / (e - sl)}
            else:
                continue
        stop = fill if half else sl
        hit_stop = b["low"] <= stop
        if not half:
            if hit_stop:                                      # stop first (conservative)
                return {"status": "STOP", "filled": fill, "closed_on": b["date"], "r": -1.0}
            if b["high"] >= t1:
                half = True
                if b["high"] >= t2:
                    return {"status": "T2", "filled": fill, "closed_on": b["date"],
                            "r": 0.5 * (t1 - fill) / risk + 0.5 * (t2 - fill) / risk}
            continue
        if hit_stop:
            return {"status": "T1_THEN_ENTRY_STOP", "filled": fill, "closed_on": b["date"],
                    "r": 0.5 * (t1 - fill) / risk}
        if b["high"] >= t2:
            return {"status": "T2", "filled": fill, "closed_on": b["date"],
                    "r": 0.5 * (t1 - fill) / risk + 0.5 * (t2 - fill) / risk}
    if fill is None:
        return {"status": "NOT_FILLED" if len(bars) >= HORIZON else "WAITING"}
    last = bars[min(len(bars), HORIZON) - 1]["close"]
    booked = 0.5 * (t1 - fill) / risk if half else 0.0
    open_part = (0.5 if half else 1.0) * (last - fill) / risk
    return {"status": "OPEN" if len(bars) < HORIZON else "TIME_EXIT", "filled": fill,
            "r": booked + open_part, "t1_hit": half}


def _view(r: dict[str, Any], bars: list[dict[str, Any]]) -> dict[str, Any]:
    c, d1, sl = r["price"], r["t1"], r["stop_loss"]
    if not bars or c is None:
        return {"status": "WAITING"}
    reached = None
    for b in bars[:VIEW_HORIZON]:
        if sl is not None and b["high"] >= sl:
            reached = "VIEW_STOP"
            break
        if d1 is not None and b["low"] <= d1:
            reached = "DOWNSIDE_1"
            break
    n = min(len(bars), VIEW_HORIZON)
    ret = bars[n - 1]["close"] / c - 1
    done = len(bars) >= VIEW_HORIZON
    return {"status": reached or ("NEITHER" if done else "OPEN"), "ret": ret,
            "complete": done}


def evaluate(records: list[dict[str, Any]], bars_by_key: dict[str, list[dict[str, Any]]]
             ) -> list[dict[str, Any]]:
    """bars_by_key: daily bars (oldest first, dicts with date/open/high/low/close)."""
    out = []
    for r in records:
        after = [b for b in bars_by_key.get(r["key"], []) if b["date"] > r["day"]]
        res = _buy(r, after) if r["action"] == "BUY" else _view(r, after)
        out.append({**r, "outcome": res, "sessions_after": len(after)})
    return out


def stats(ev: list[dict[str, Any]]) -> dict[str, Any]:
    buys = [x for x in ev if x["action"] == "BUY"]
    closed = [x for x in buys if x["outcome"]["status"] in
              ("STOP", "T2", "T1_THEN_ENTRY_STOP", "TIME_EXIT", "GAP_BELOW_STOP")]
    rs = [x["outcome"]["r"] for x in closed]
    by: dict[str, int] = {}
    for x in buys:
        by[x["outcome"]["status"]] = by.get(x["outcome"]["status"], 0) + 1
    views = [x for x in ev if x["action"] == "SELL / AVOID" and x["outcome"].get("complete")]
    vr = [x["outcome"]["ret"] for x in views]
    return {"buy": {"plans": len(buys), "by_status": by, "closed": len(closed),
                    "win_rate": (sum(r > 0 for r in rs) / len(rs)) if rs else None,
                    "avg_r": (sum(rs) / len(rs)) if rs else None},
            "sell_avoid": {"views": len([x for x in ev if x["action"] == "SELL / AVOID"]),
                           "complete": len(views),
                           "fell": (sum(r < 0 for r in vr) / len(vr)) if vr else None,
                           "avg_5d_return": (sum(vr) / len(vr)) if vr else None},
            "days": sorted({x["day"] for x in ev}),
            "note": "Forward record from 2026-10-22. R = multiples of the plan's risk; costs "
                    "and slippage not included; a session touching stop and target counts "
                    "as the stop. Paper research only."}
