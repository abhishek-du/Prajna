"""Research Desk queries for the dashboard (read only). The watchlist with each suggestion's
live state, the latest verdicts (sortable by score), one stock's dossier and verdict history,
the watchlist log and accuracy by score bucket."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.desk import config as K
from app.desk import watchlist as WL


def _n(x: Any) -> Any:
    if hasattr(x, "as_tuple"):
        v = float(x)
        return v if math.isfinite(v) else None
    return x


def _row(r: Any) -> dict[str, Any]:
    return {k: _n(v) for k, v in dict(r).items()}


async def watch(s: AsyncSession) -> dict[str, Any]:
    act = await WL.active(s)
    ids = [v["verdict_id"] for v in act.values()]
    ev: dict[int, list] = defaultdict(list)
    if ids:
        for r in (await s.execute(text("""select verdict_id, kind, price, at from
                desk_track_event where verdict_id = any(:i) order by at"""),
                {"i": ids})).mappings().all():
            ev[r["verdict_id"]].append(_row(r))
    rows = []
    for k, v in act.items():
        vv = {x: _n(y) for x, y in v.items()}
        vv["key"] = k
        vv["events"] = ev.get(v["verdict_id"], [])
        rows.append(vv)
    rows.sort(key=lambda r: -(r.get("score") or 0))
    return {"watchlist": rows, "add_score": K.ADD_SCORE, "remove_score": K.REMOVE_SCORE,
            "disclaimer": K.DISCLAIMER}


async def latest_run(s: AsyncSession) -> dict[str, Any] | None:
    r = (await s.execute(text("""select run_id, kind, session_date, counts, created_at
        from desk_run order by created_at desc limit 1"""))).mappings().first()
    return _row(r) if r else None


async def verdicts(s: AsyncSession, decision: str | None = None, limit: int = 600
                   ) -> dict[str, Any]:
    """The latest verdict per stock (from any run in the last 3 days)."""
    rows = (await s.execute(text("""select distinct on (v.instrument_key) v.id, v.instrument_key,
            v.symbol, v.session_date, v.status, v.decision, v.horizon, v.score, v.pov,
            v.entry_lo, v.entry_hi, v.stop, v.t1, v.t2, v.rule_decision, v.rule_flags,
            v.conflicts, v.why_moved->>'driver' driver, v.why_moved->>'summary' why,
            v.created_at, r.kind
        from desk_verdict v join desk_run r using (run_id)
        where v.created_at > now() - interval '3 days'
        order by v.instrument_key, v.created_at desc"""))).mappings().all()
    out = [_row(r) for r in rows if decision is None or r["decision"] == decision]
    out.sort(key=lambda r: -(r.get("score") or -1))
    mix: dict[str, int] = defaultdict(int)
    for r in rows:
        mix[r["decision"] or r["status"]] += 1
    return {"verdicts": out[:limit], "mix": dict(mix), "run": await latest_run(s)}


async def stock(s: AsyncSession, key: str) -> dict[str, Any] | None:
    hist = [_row(r) for r in (await s.execute(text("""select v.*, r.kind from desk_verdict v
        join desk_run r using (run_id) where v.instrument_key = :k
        order by v.created_at desc limit 15"""), {"k": key})).mappings().all()]
    if not hist:
        return None
    cur = hist[0]
    pk = (await s.execute(text("select packet from desk_dossier where id = :i"),
                          {"i": cur["dossier_id"]})).scalar()
    tracks = [_row(r) for r in (await s.execute(text("""select verdict_id, kind, price, at
        from desk_track_event where instrument_key = :k order by at desc limit 30"""),
        {"k": key})).mappings().all()]
    wl = [_row(r) for r in (await s.execute(text("""select event, reason, score, decision,
        created_at from desk_watch_event where instrument_key = :k order by id desc limit 20"""),
        {"k": key})).mappings().all()]
    for h in hist:
        h.pop("response_raw", None)
    return {"verdict": cur, "dossier": pk, "history": hist[1:], "tracks": tracks,
            "watch_log": wl, "on_watchlist": key in await WL.active(s),
            "disclaimer": K.DISCLAIMER}


async def log(s: AsyncSession, limit: int = 200) -> list[dict[str, Any]]:
    return [_row(r) for r in (await s.execute(text("""select id, instrument_key, symbol, event,
        reason, score, decision, created_at from desk_watch_event order by id desc limit :n"""),
        {"n": limit})).mappings().all()]


async def accuracy(s: AsyncSession) -> dict[str, Any]:
    """Every suggestion that reached a watchlist: did it trigger, and how did it end, by score
    bucket. Counts only; the per-trade P&L is in Strategy Lab (desk_llm_v1)."""
    rows = (await s.execute(text("""select v.id, v.score, v.decision,
            array_agg(t.kind) filter (where t.kind is not null) kinds
        from desk_verdict v join desk_watch_event w on w.verdict_id = v.id and w.event = 'ADD'
        left join desk_track_event t on t.verdict_id = v.id
        group by v.id, v.score, v.decision"""))).mappings().all()
    buckets: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in rows:
        b = "90+" if r["score"] >= 90 else "80-89" if r["score"] >= 80 else "70-79"
        ks = set(r["kinds"] or [])
        buckets[b]["added"] += 1
        for kind in ("ENTRY_TRIGGERED", "T1", "T2", "STOP", "INVALIDATED", "EXPIRED"):
            buckets[b][kind] += kind in ks
    return {"buckets": {b: dict(v) for b, v in sorted(buckets.items())},
            "note": "A suggestion is judged only after it ends; small counts are noise."}
