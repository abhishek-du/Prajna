"""The auto-managed watchlist (pure transitions + DB reads). The current list is derived from
desk_watch_event: a stock is on the list after an ADD/UPDATE and off it after a REMOVE.

ADD     a valid verdict, decision BUY/STRONG_BUY, score >= ADD_SCORE
UPDATE  a newer valid verdict that keeps it (new levels and score)
REMOVE  score < REMOVE_SCORE or decision AVOID/SELL; stop hit; T2 hit; invalidated before
        entry; an intraday suggestion expired; no fresh verdict for STALE_SESSIONS sessions
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.desk import config as K

END_EVENTS = {"STOP": "stop-loss hit", "T2": "target 2 reached",
              "INVALIDATED": "invalidated before entry (price fell through the stop)",
              "EXPIRED": "intraday suggestion expired at 15:15"}


def transitions(active: dict[str, dict[str, Any]], verdicts: list[dict[str, Any]],
                *, sessions_since: dict[str, int] | None = None,
                ended: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """active: key -> {verdict_id, score, decision} of the list now; verdicts: this run's
    verdicts (id, instrument_key, symbol, status, decision, score); sessions_since: key ->
    sessions since its active verdict; ended: key -> the track event that ended it."""
    out: list[dict[str, Any]] = []
    gone: set[str] = set()
    for k, kind in (ended or {}).items():
        if k in active:
            out.append({"instrument_key": k, "event": "REMOVE", "reason": END_EVENTS[kind],
                        "verdict_id": active[k]["verdict_id"], "score": active[k].get("score"),
                        "decision": active[k].get("decision"), "symbol": active[k].get("symbol")})
            gone.add(k)
    for v in verdicts:
        k = v["instrument_key"]
        if k in gone or v["status"] != "OK":
            continue
        base = {"instrument_key": k, "symbol": v.get("symbol"), "verdict_id": v["id"],
                "score": v["score"], "decision": v["decision"]}
        buy = v["decision"] in K.BUY_DECISIONS
        if k not in active:
            if buy and v["score"] >= K.ADD_SCORE:
                out.append({**base, "event": "ADD",
                            "reason": f"{v['decision']} with score {v['score']} "
                                      f"(>= {K.ADD_SCORE})"})
            continue
        if v["score"] < K.REMOVE_SCORE or v["decision"] in ("AVOID", "SELL"):
            out.append({**base, "event": "REMOVE",
                        "reason": f"new verdict {v['decision']} score {v['score']}"})
        else:
            out.append({**base, "event": "UPDATE",
                        "reason": f"refreshed: {v['decision']} score {v['score']}"})
        gone.add(k)
    for k, n in (sessions_since or {}).items():
        if k in active and k not in gone and n >= K.STALE_SESSIONS:
            out.append({"instrument_key": k, "event": "REMOVE", "symbol": active[k].get("symbol"),
                        "reason": f"no fresh verdict for {n} sessions",
                        "verdict_id": active[k]["verdict_id"], "score": active[k].get("score"),
                        "decision": active[k].get("decision")})
    return out


async def active(s: AsyncSession) -> dict[str, dict[str, Any]]:
    """The current list with each entry's active verdict."""
    rows = (await s.execute(text("""select distinct on (e.instrument_key) e.instrument_key,
            e.event, e.verdict_id, e.created_at as since, e.symbol
        from desk_watch_event e order by e.instrument_key, e.id desc"""))).mappings().all()
    on = {r["instrument_key"]: dict(r) for r in rows if r["event"] in ("ADD", "UPDATE")}
    if not on:
        return {}
    vs = (await s.execute(text("""select id, instrument_key, symbol, session_date, decision,
            score, horizon, entry_lo, entry_hi, stop, t1, t2, created_at from desk_verdict
        where id = any(:i)"""), {"i": [r["verdict_id"] for r in on.values()]})).mappings().all()
    byid = {v["id"]: dict(v) for v in vs}
    added = {r["instrument_key"]: r["since"] for r in (await s.execute(text("""
        select instrument_key, max(created_at) since from desk_watch_event where event = 'ADD'
        group by 1"""))).mappings().all()}
    out = {}
    for k, r in on.items():
        v = byid.get(r["verdict_id"]) or {}
        out[k] = {**v, "verdict_id": r["verdict_id"], "symbol": r["symbol"] or v.get("symbol"),
                  "added_at": added.get(k), "updated_at": r["since"]}
    return out


async def sessions_since(s: AsyncSession, act: dict[str, dict], today: _dt.date) -> dict[str, int]:
    out = {}
    for k, v in act.items():
        d = v.get("session_date")
        if d is None:
            continue
        out[k] = (await s.execute(text("""select count(*) from trading_session
            where is_trading_day and session_date > :a and session_date <= :b"""),
            {"a": d, "b": today})).scalar()
    return out


async def record(s: AsyncSession, events: list[dict[str, Any]]) -> int:
    if events:
        await s.execute(text("""insert into desk_watch_event (instrument_key, symbol, event,
            reason, verdict_id, score, decision) values (:instrument_key, :symbol, :event,
            :reason, :verdict_id, :score, :decision)"""),
            [{"symbol": None, **e} for e in events])
    return len(events)
