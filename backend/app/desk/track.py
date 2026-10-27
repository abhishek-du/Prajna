"""Live tracking of the watchlist's suggestions (long only). Each 30-second Upstox quote is
compared with the active verdict's levels; each event is written once (desk_track_event,
unique per verdict and kind); an ending event removes the stock from the watchlist.

  before entry   price <= stop                      INVALIDATED
                 entry_lo <= price <= entry_hi      ENTRY_TRIGGERED
  after entry    price <= stop                      STOP
                 price >= t1                        T1
                 price >= t2                        T2 (and T1 if not yet)
  intraday       15:15 IST without an exit          EXPIRED
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import IST
from app.desk import watchlist as WL

EXPIRE_AT = _dt.time(15, 15)
ENDING = ("STOP", "T2", "INVALIDATED", "EXPIRED")


def _f(x: Any) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def evaluate(v: dict[str, Any], done: set[str], price: float | None,
             at: _dt.datetime) -> list[str]:
    """New event kinds for one suggestion at one price (pure)."""
    lo, hi, sl, t1, t2 = (_f(v.get(k)) for k in ("entry_lo", "entry_hi", "stop", "t1", "t2"))
    if price is None or None in (lo, hi, sl, t1, t2) or done & set(ENDING):
        return []
    out: list[str] = []
    if "ENTRY_TRIGGERED" not in done:
        if price <= sl:
            out.append("INVALIDATED")
        elif lo <= price <= hi:
            out.append("ENTRY_TRIGGERED")
        elif v.get("horizon") == "INTRADAY" and at.astimezone(IST).time() >= EXPIRE_AT:
            out.append("EXPIRED")
        return out
    if price <= sl:
        return ["STOP"]
    if price >= t2:
        return ([] if "T1" in done else ["T1"]) + ["T2"]
    if price >= t1 and "T1" not in done:
        out.append("T1")
    if v.get("horizon") == "INTRADAY" and at.astimezone(IST).time() >= EXPIRE_AT:
        out.append("EXPIRED")
    return out


async def tick(s: AsyncSession, quote, at: _dt.datetime) -> list[dict[str, Any]]:
    """One pass over the watchlist. `quote(key)` returns a live quote or None. Returns the
    new events (for Telegram)."""
    act = await WL.active(s)
    if not act:
        return []
    ids = [v["verdict_id"] for v in act.values()]
    done: dict[int, set[str]] = {}
    for r in (await s.execute(text("""select verdict_id, kind from desk_track_event
            where verdict_id = any(:i)"""), {"i": ids})).all():
        done.setdefault(r.verdict_id, set()).add(r.kind)
    new: list[dict[str, Any]] = []
    ended: dict[str, str] = {}
    for k, v in act.items():
        if v.get("decision") not in ("BUY", "STRONG_BUY"):
            continue
        if v.get("created_at") and v["created_at"] > at:
            continue
        q = quote(k)
        price = _f((q or {}).get("ltp"))
        for kind in evaluate(v, done.get(v["verdict_id"], set()), price, at):
            r = (await s.execute(text("""insert into desk_track_event (verdict_id,
                instrument_key, symbol, kind, price, at, source) values (:v, :k, :s, :kind,
                :p, :a, 'UPSTOX_QUOTE') on conflict (verdict_id, kind) do nothing
                returning id"""), {"v": v["verdict_id"], "k": k, "s": v.get("symbol"),
                                   "kind": kind, "p": price, "a": at})).scalar()
            if r:
                new.append({"key": k, "symbol": v.get("symbol"), "kind": kind, "price": price,
                            "verdict": v})
                if kind in ENDING:
                    ended[k] = kind
    if ended:
        await WL.record(s, WL.transitions(act, [], ended=ended))
    await s.commit()
    return new


def message(e: dict[str, Any]) -> str:
    v = e["verdict"]
    lvl = (f"entry {float(v['entry_lo']):,.2f}-{float(v['entry_hi']):,.2f}, stop "
           f"{float(v['stop']):,.2f}, T1 {float(v['t1']):,.2f}, T2 {float(v['t2']):,.2f}")
    what = {"ENTRY_TRIGGERED": "entry zone reached", "T1": "target 1 reached",
            "T2": "target 2 reached (removed)", "STOP": "stop-loss hit (removed)",
            "INVALIDATED": "fell through the stop before entry (removed)",
            "EXPIRED": "intraday suggestion expired (removed)"}[e["kind"]]
    return (f"{e['symbol']} {e['price']:,.2f}: {what} | {v.get('decision')} score "
            f"{v.get('score')} | {lvl}")
