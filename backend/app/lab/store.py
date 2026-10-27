"""Strategy Lab writes: one lab_run per (kind, session, content). A rebuild with the same
inputs writes nothing (UNCHANGED); different inputs write a new run, and readers take the
latest. Needs the write token. Tables are append-only (trigger)."""

from __future__ import annotations

import datetime as _dt
import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import authorize_write
from app.lab.compute import LAB_VERSION


def _j(x: Any) -> str:
    return json.dumps(x, default=str, sort_keys=True)


async def latest_sha(s: AsyncSession, kind: str, day: _dt.date) -> str | None:
    return (await s.execute(text("""select inputs_sha256 from lab_run where kind = :k
        and session_date = :d order by created_at desc limit 1"""),
        {"k": kind, "d": day})).scalar()


async def _run(s: AsyncSession, kind: str, day: _dt.date, sha: str, counts: dict,
               code_git_sha: str) -> uuid.UUID:
    rid = uuid.uuid4()
    await s.execute(text("""insert into lab_run (run_id, kind, session_date, lab_version,
        inputs_sha256, counts, code_git_sha) values (:r, :k, :d, :v, :s, cast(:c as jsonb), :g)"""),
        {"r": rid, "k": kind, "d": day, "v": LAB_VERSION, "s": sha, "c": _j(counts),
         "g": code_git_sha})
    return rid


async def record_daily(s: AsyncSession, out: dict[str, Any], *, token: str | None,
                       code_git_sha: str) -> dict[str, Any]:
    authorize_write(token)
    day = out["session"]
    if not out["days"] and not out["trades"]:
        return {"session": day, "status": "NOTHING"}
    if await latest_sha(s, "DAILY", day) == out["inputs_sha256"]:
        return {"session": day, "status": "UNCHANGED"}
    rid = await _run(s, "DAILY", day, out["inputs_sha256"], out["counts"], code_git_sha)
    base = {"r": rid, "d": day}
    if out["days"]:
        await s.execute(text("""insert into strategy_day (run_id, session_date, strategy,
            family, enabled, trades, wins, losses, gross_inr, charges_inr, net_inr, net_r,
            placebo_trades, placebo_net_inr, regime_pre, regime_open, day_type, equity_inr,
            drawdown, detail) values (:r, :d, :strategy, :family, :enabled, :trades, :wins,
            :losses, :gross_inr, :charges_inr, :net_inr, :net_r, :placebo_trades,
            :placebo_net_inr, :regime_pre, :regime_open, :day_type, :equity_inr, :drawdown,
            cast(:detail as jsonb))"""),
            [{**base, **{k: v for k, v in x.items() if k != "detail"}, "detail": _j(x["detail"])}
             for x in out["days"]])
    if out["trades"]:
        cols = ("strategy", "family", "source", "source_id", "instrument_key", "symbol",
                "sector", "side", "is_placebo", "signal_at", "entry_at", "exit_at", "entry_px",
                "exit_px", "stop", "target", "qty", "net_inr", "net_r", "exit_reason",
                "outcome_class", "outcome_rule", "mfe_pct", "mae_pct", "mfe_r", "mae_r",
                "target_after_exit", "regime_state", "day_type", "ai_verdict",
                "first_news_lag_min")
        js = ("news_before", "news_after", "plan", "path")
        await s.execute(text(f"""insert into trade_forensic (run_id, session_date,
            {", ".join(cols + js)}) values (:r, :d, {", ".join(":" + c for c in cols)},
            {", ".join(f"cast(:{c} as jsonb)" for c in js)})"""),  # noqa: S608
            [{**base, **{c: t.get(c) for c in cols}, **{c: _j(t.get(c) or ([] if c.startswith(
                "news") else {})) for c in js}} for t in out["trades"]])
    if out["forensics"]:
        await s.execute(text("""insert into day_forensic (run_id, session_date, strategy,
            thought, happened, why, narrative) values (:r, :d, :s, cast(:t as jsonb),
            cast(:h as jsonb), cast(:w as jsonb), cast(:n as jsonb))"""),
            [{**base, "s": f["strategy"], "t": _j(f["thought"]), "h": _j(f["happened"]),
              "w": _j(f["why"]), "n": None if f.get("narrative") is None
              else _j(f["narrative"])} for f in out["forensics"]])
    await s.commit()
    return {"session": day, "status": "WRITTEN", "run_id": str(rid), "counts": out["counts"]}


async def record_brief(s: AsyncSession, brief: dict[str, Any], *, token: str | None,
                       code_git_sha: str) -> dict[str, Any]:
    authorize_write(token)
    day = brief["session"]
    if await latest_sha(s, "BRIEF", day) == brief["inputs_sha256"]:
        return {"session": day, "status": "UNCHANGED"}
    rid = await _run(s, "BRIEF", day, brief["inputs_sha256"], brief["counts"], code_git_sha)
    await s.execute(text("""insert into daily_brief (run_id, session_date, regime, events,
        candidates, news, disclaimer) values (:r, :d, cast(:g as jsonb), cast(:e as jsonb),
        cast(:c as jsonb), cast(:n as jsonb), :x)"""),
        {"r": rid, "d": day, "g": _j(brief["regime"]), "e": _j(brief["events"]),
         "c": _j(brief["candidates"]), "n": _j(brief["news"]), "x": brief["disclaimer"]})
    await s.commit()
    return {"session": day, "status": "WRITTEN", "run_id": str(rid), "counts": brief["counts"]}
