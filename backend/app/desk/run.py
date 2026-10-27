"""A Research Desk run: build the dossiers, investigate each stock (bounded concurrency),
store everything, then update the watchlist. Needs the write token to commit; a dry run
investigates and returns the verdicts without writing (the LLM calls still cost)."""

from __future__ import annotations

import asyncio
import datetime as _dt
import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import authorize_write
from app.desk import config as K
from app.desk import dossier as DS
from app.desk import investigate as INV
from app.desk import watchlist as WL


def _j(x: Any) -> str:
    return json.dumps(x, default=str, sort_keys=True)


async def changed_keys(s: AsyncSession, session: _dt.date, since: _dt.datetime) -> list[str]:
    """MORNING: names with news, results or corporate actions knowable since `since`, plus
    the watchlist."""
    rows = (await s.execute(text("""select distinct l.instrument_key from news_entity_link l
        join news_item i on i.id = l.item_id where greatest(l.knowable_at, i.knowable_at) > :t
          and l.confidence >= 0.8
        union select instrument_key from results_event where knowable_at > :t
          and instrument_key is not null
        union select instrument_key from canon_corporate_action where ex_date = :d"""),
        {"t": since, "d": session})).scalars().all()
    return sorted(set(rows) | set(await WL.active(s)))


async def plan_keys(s: AsyncSession, session: _dt.date, mode: str
                    ) -> tuple[list[str] | None, dict | None, dict | None, list[str]]:
    """(keys, live quotes, regime override, extra keys) for a mode. EVENING: the universe
    (ranked in the dossier) plus the watchlist. MORNING: names with overnight news/events
    plus the watchlist. INTRADAY: the watchlist plus the 20 largest live movers of the last
    evening universe."""
    wl = sorted(await WL.active(s))
    if mode == "EVENING":
        return None, None, None, wl
    last = (await s.execute(text("""select r.run_id, r.created_at from desk_run r
        where r.kind = 'EVENING' order by r.created_at desc limit 1"""))).first()
    reg = None
    uni: list[str] = []
    if last is not None:
        reg = (await s.execute(text("""select packet->'evidence'->'ctx'->'regime'
            from desk_dossier where run_id = :r limit 1"""), {"r": last.run_id})).scalar()
        uni = list((await s.execute(text("""select instrument_key from desk_dossier
            where run_id = :r"""), {"r": last.run_id})).scalars())
    if mode == "MORNING":
        since = last.created_at if last is not None else \
            _dt.datetime.combine(session - _dt.timedelta(days=1), _dt.time(14, 0), _dt.UTC)
        return await changed_keys(s, session, since), None, reg, []
    live = await DS.quotes([*sorted(set(uni) | set(wl)), "NSE_INDEX|Nifty 50"])
    movers = sorted((k for k in uni if (live.get(k) or {}).get("change") is not None),
                    key=lambda k: -abs(live[k]["change"]))[:20]
    return sorted(set(wl) | set(movers)), live, reg, []


async def execute(s: AsyncSession, session: _dt.date, mode: str, model, *, commit: bool,
                  token: str | None, code_git_sha: str, keys: list[str] | None = None,
                  live: dict[str, dict] | None = None, limit: int | None = None,
                  concurrency: int = K.CONCURRENCY, progress=None,
                  regime: dict | None = None, extra: list[str] | tuple = ()) -> dict[str, Any]:
    if commit:
        authorize_write(token)               # before any model call
    built = await DS.build(s, session, mode, keys=keys, live=live, extra=extra,
                           regime_override=regime)
    await s.rollback()                       # release the read snapshot before the slow part
    dossiers = list(built["dossiers"].items())
    if limit:
        dossiers = dossiers[:limit]
    sem = asyncio.Semaphore(concurrency)
    done = 0

    async def one(k, d):
        nonlocal done
        async with sem:
            v = await INV.investigate(model, d["packet"])
        done += 1
        if progress and done % 25 == 0:
            progress(done, len(dossiers))
        return k, d, v

    results = await asyncio.gather(*(one(k, d) for k, d in dossiers))
    mix: dict[str, int] = {}
    for _, _, v in results:
        key = v["status"] if v["status"] != "OK" else v["decision"]
        mix[key] = mix.get(key, 0) + 1
    counts = {"universe": built["universe"], "investigated": len(results), "mix": mix,
              "conflicts": sum(1 for *_, v in results if v.get("conflicts")),
              "latency_ms_mean": int(sum(v["latency_ms"] for *_, v in results)
                                     / max(1, len(results)))}
    if not commit:
        return {"session": session, "mode": mode, "status": "DRY_RUN", "counts": counts,
                "verdicts": [{"key": k, "symbol": d["symbol"], **{x: v.get(x) for x in (
                    "status", "decision", "score", "conflicts", "rule_decision")}}
                             for k, d, v in results]}
    rid = uuid.uuid4()
    await s.execute(text("""insert into desk_run (run_id, kind, session_date, desk_version,
        model_id, prompt_version, counts, code_git_sha) values (:r, :k, :d, :v, :m, :p,
        cast(:c as jsonb), :g)"""),
        {"r": rid, "k": mode, "d": session, "v": K.DESK_VERSION, "m": K.MODEL_ID,
         "p": K.PROMPT_VERSION, "c": _j(counts), "g": code_git_sha})
    stored = []
    for k, d, v in results:
        did = (await s.execute(text("""insert into desk_dossier (run_id, instrument_key, symbol,
            packet, packet_sha256) values (:r, :k, :s, cast(:p as jsonb), :h) returning id"""),
            {"r": rid, "k": k, "s": d["symbol"], "p": _j(d["packet"]), "h": d["sha"]})).scalar()
        lb = dict(v.get("levels_basis") or {})
        if v.get("rule_disagreement"):
            lb["rule_disagreement"] = v["rule_disagreement"]
        vid = (await s.execute(text("""insert into desk_verdict (run_id, dossier_id, session_date,
            instrument_key, symbol, status, invalid_reason, decision, horizon, score, pov,
            entry_lo, entry_hi, stop, t1, t2, levels_basis, why_moved, thesis, risks,
            invalidation, evidence_ids, rule_decision, rule_flags, rule_plan, conflicts,
            model_id, prompt_sha256, response_raw, latency_ms) values (:r, :di, :d, :k, :s, :st,
            :ir, :de, :ho, :sc, cast(:po as jsonb), :el, :eh, :sl, :t1, :t2, cast(:lb as jsonb),
            cast(:wm as jsonb), :th, cast(:ri as jsonb), :inv, :ei, :rd, :rf, cast(:rp as jsonb),
            :cf, :mi, :ps, :raw, :lat) returning id"""),
            {"r": rid, "di": did, "d": session, "k": k, "s": d["symbol"], "st": v["status"],
             "ir": v.get("invalid_reason"), "de": v.get("decision"), "ho": v.get("horizon"),
             "sc": v.get("score"), "po": _j(v.get("pov")) if v.get("pov") else None,
             "el": v.get("entry_lo"), "eh": v.get("entry_hi"), "sl": v.get("stop"),
             "t1": v.get("t1"), "t2": v.get("t2"), "lb": _j(lb) if lb else None,
             "wm": _j(v.get("why_moved")) if v.get("why_moved") else None,
             "th": v.get("thesis"), "ri": _j(v.get("risks")) if v.get("risks") is not None
             else None, "inv": v.get("invalidation"), "ei": v.get("evidence_ids") or [],
             "rd": v["rule_decision"], "rf": v["rule_flags"], "rp": _j(v["rule_plan"]),
             "cf": v.get("conflicts") or [], "mi": v["model_id"], "ps": v["prompt_sha256"],
             "raw": v.get("response_raw"), "lat": v.get("latency_ms")})).scalar()
        stored.append({"id": vid, "instrument_key": k, "symbol": d["symbol"], **{
            x: v.get(x) for x in ("status", "decision", "score")}})
    act = await WL.active(s)
    ev = WL.transitions(act, stored, sessions_since=await WL.sessions_since(s, act, session))
    await WL.record(s, ev)
    await s.commit()
    return {"session": session, "mode": mode, "status": "WRITTEN", "run_id": str(rid),
            "counts": counts, "watchlist_events": ev}
