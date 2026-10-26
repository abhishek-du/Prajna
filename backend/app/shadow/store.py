"""Record a shadow session (migration 0027) and register the frozen policy.

- A commit needs the write token, a frozen policy row whose spec sha equals the code's,
  and a session on or after the policy's forward start.
- Idempotent per (policy, session): the same rows again -> ALREADY_PRESENT, nothing
  written; different rows -> refused (a stored shadow day is never overwritten).
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import authorize_write
from app.core.clock import now
from app.shadow import job as J
from app.shadow import spec as SP


def _d(x: float | None) -> Decimal | None:
    return None if x is None else Decimal(str(round(float(x), 4)))


def _j(x: Any) -> str:
    return json.dumps(x, default=str, sort_keys=True)


async def policy(s: AsyncSession) -> Any:
    return (await s.execute(text("""select policy_version, spec_sha256, forward_from,
        event_calendar_sha256 from shadow_policy where policy_version = :v"""),
        {"v": SP.POLICY_VERSION})).first()


async def freeze(s: AsyncSession, *, forward_from: _dt.date, token: str | None,
                 code_git_sha: str) -> dict[str, Any]:
    fp = authorize_write(token)
    if SP.FORWARD_FROM != forward_from:
        raise J.ShadowRefused(f"spec.FORWARD_FROM is {SP.FORWARD_FROM}, not {forward_from}: "
                              "set it in the frozen code first")
    old = await policy(s)
    if old is not None:
        if old.spec_sha256 != SP.spec_sha256():
            raise J.ShadowRefused(f"{SP.POLICY_VERSION} is frozen with another spec; "
                                  "a change is a new policy version")
        return {"status": "ALREADY_PRESENT", "policy_version": SP.POLICY_VERSION}
    _, cal_sha = J.calendar()
    await s.execute(text("""insert into shadow_policy (policy_version, spec, spec_sha256,
        code_git_sha, event_calendar_sha256, forward_from, frozen_at, authz_token_sha256)
        values (:v, cast(:sp as jsonb), :sh, :g, :c, :f, :n, :a)"""),
        {"v": SP.POLICY_VERSION, "sp": _j(SP.spec()), "sh": SP.spec_sha256(),
         "g": code_git_sha, "c": cal_sha, "f": forward_from, "n": now(), "a": fp})
    await s.commit()
    return {"status": "WRITTEN", "policy_version": SP.POLICY_VERSION,
            "spec_sha256": SP.spec_sha256(), "forward_from": str(forward_from)}


async def prior_daily_net(s: AsyncSession, before: _dt.date) -> dict[str, list[float]]:
    rows = (await s.execute(text("""select strategy, market_date, sum(net_inr) from shadow_trade
        where policy_version = :v and not is_placebo and market_date < :b
        group by 1, 2 order by 1, 2"""), {"v": SP.POLICY_VERSION, "b": before})).all()
    out: dict[str, list[float]] = {}
    for r in rows:
        out.setdefault(r[0], []).append(float(r[2]))
    return out


async def pending(s: AsyncSession) -> list[_dt.date]:
    """The sessions from the forward start (or after the last stored run) whose 1d and 1m
    bars are stored, in order; a session not ready yet ends the list (catch-up keeps order)."""
    pol = await policy(s)
    if pol is None:
        return []
    last = (await s.execute(text("""select max(market_date) from shadow_run
        where policy_version = :v"""), {"v": SP.POLICY_VERSION})).scalar()
    days = (await s.execute(text("""select session_date from trading_session
        where is_trading_day and session_date >= :f and session_date > :l
          and session_date <= :t order by 1"""),
        {"f": pol.forward_from, "l": last or _dt.date.min,
         "t": now().astimezone(J.IST).date()})).scalars().all()
    out = []
    for d in days:
        if await J.ready(s, d):
            break
        out.append(d)
    return out


async def record(s: AsyncSession, session: _dt.date, inp: dict[str, Any], out: dict[str, Any],
                 *, cutoff: _dt.datetime, token: str | None,
                 code_git_sha: str) -> dict[str, Any]:
    fp = authorize_write(token)
    pol = await policy(s)
    if pol is None or pol.spec_sha256 != SP.spec_sha256():
        raise J.ShadowRefused(f"{SP.POLICY_VERSION} is not frozen with this code's spec")
    if session < pol.forward_from:
        raise J.ShadowRefused(f"{session} is before the forward start {pol.forward_from}")
    skipped = inp.get("skipped")
    rows_sha = J.rows_sha256(out) if not skipped else hashlib.sha256(
        skipped.encode()).hexdigest()
    old = (await s.execute(text("""select run_id, rows_sha256 from shadow_run
        where policy_version = :v and market_date = :d"""),
        {"v": SP.POLICY_VERSION, "d": session})).first()
    if old is not None:
        if old.rows_sha256 != rows_sha:
            raise J.ShadowRefused(f"{session} is stored with other rows (run {old.run_id}); "
                                  "a shadow day is never overwritten")
        return {"status": "ALREADY_PRESENT", "run_id": str(old.run_id)}
    rid = uuid.uuid4()
    base = {"r": rid, "v": SP.POLICY_VERSION, "d": session}
    await s.execute(text("""insert into shadow_run (run_id, policy_version, market_date, status,
        reason, cutoff, inputs_sha256, rows_sha256, counts, code_git_sha, authz_token_sha256,
        created_at) values (:r, :v, :d, :st, :re, :c, :i, :rs, cast(:n as jsonb), :g, :a, :t)"""),
        {**base, "st": "SKIPPED" if skipped else "DONE", "re": skipped, "c": cutoff,
         "i": inp.get("inputs_sha256") or rows_sha, "rs": rows_sha,
         "n": _j({} if skipped else out["counts"]), "g": code_git_sha, "a": fp, "t": now()})
    if skipped:
        await s.commit()
        return {"status": "WRITTEN_SKIPPED", "run_id": str(rid), "reason": skipped}
    await s.execute(text("""insert into regime_snapshot (run_id, policy_version, market_date,
        checkpoint, features, state, rule_fired, risk_mult, day_type) values
        (:r, :v, :d, :cp, cast(:f as jsonb), :st, :ru, :m, :dt)"""),
        [{**base, "cp": z["checkpoint"], "f": _j(z["features"]), "st": z["state"],
          "ru": z["rule_fired"], "m": z["risk_mult"], "dt": z["day_type"]}
         for z in out["snapshots"]])
    if out["trades"]:
        await s.execute(text("""insert into shadow_trade (run_id, policy_version, market_date,
            strategy, instrument_key, side, is_placebo, signal_at, entry_at, exit_at, time_stop,
            entry_raw, stop, target, atr, qty, size_factor, risk_inr, rrr, checklist,
            checklist_score, exit_raw, exit_reason, entry_px, exit_px, gross_inr, charges,
            net_inr, net_r, by_slippage, sector, regime_state, risk_mult, day_type, guard_flags,
            evidence, mode) values (:r, :v, :d, :s, :k, :sd, :p, :sa, :ea, :xa, :ts, :er, :sp,
            :tg, :at, :q, :sf, :ri, :rr, cast(:cl as jsonb), :cs, :xr, :xn, :ep, :xp, :gi,
            cast(:ch as jsonb), :ni, :nr, cast(:bs as jsonb), :se, :rs, :rm, :dt, :gf,
            cast(:ev as jsonb), 'SHADOW')"""),
            [{**base, "s": x["strategy"], "k": x["instrument_key"], "sd": x["side"],
              "p": x["is_placebo"], "sa": x["signal_at"], "ea": x["entry_at"],
              "xa": x["exit_at"], "ts": x["time_stop"], "er": _d(x["entry_raw"]),
              "sp": _d(x["stop"]), "tg": _d(x["target"]), "at": x["atr"], "q": x["qty"],
              "sf": x["size_factor"], "ri": _d(x["risk_inr"]), "rr": x["rrr"],
              "cl": _j(x["checklist"]), "cs": x["checklist_score"], "xr": _d(x["exit_raw"]),
              "xn": x["exit_reason"], "ep": _d(x["entry_px"]), "xp": _d(x["exit_px"]),
              "gi": _d(x["gross_inr"]), "ch": _j(x["charges"]), "ni": _d(x["net_inr"]),
              "nr": x["net_r"], "bs": _j(x["by_slippage"]), "se": x["sector"],
              "rs": x["regime_state"], "rm": x["risk_mult"], "dt": x["day_type"],
              "gf": x["guard_flags"], "ev": _j(x["evidence"])} for x in out["trades"]])
    if out["skips"]:
        await s.execute(text("""insert into shadow_skip (run_id, policy_version, market_date,
            strategy, instrument_key, reason, signal_at, detail) values
            (:r, :v, :d, :s, :k, :re, :sa, cast(:de as jsonb))"""),
            [{**base, "s": z["strategy"], "k": z["instrument_key"], "re": z["reason"],
              "sa": z["signal_at"], "de": _j(z["detail"])} for z in out["skips"]])
    await s.commit()
    return {"status": "WRITTEN", "run_id": str(rid), "counts": out["counts"]}
