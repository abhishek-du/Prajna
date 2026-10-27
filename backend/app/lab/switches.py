"""Strategy on/off switches (strategy_switch, append-only). The latest row per strategy is
its state; no row means the registry default (what was scheduled before the lab). Every
change needs the write token and a reason, and stays in the table as the audit log."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import authorize_write
from app.core.errors import PrajnaError
from app.lab import registry as RG


class SwitchRefused(PrajnaError):
    """The switch request is not allowed."""


async def current(s: AsyncSession) -> dict[str, dict[str, Any]]:
    rows = (await s.execute(text("""select distinct on (strategy) strategy, enabled, reason,
        created_at from strategy_switch order by strategy, id desc"""))).all()
    got = {r.strategy: {"enabled": r.enabled, "reason": r.reason, "at": r.created_at}
           for r in rows}
    return {n: got.get(n, {"enabled": RG.BY_NAME[n].default_on, "reason": None, "at": None})
            for n in RG.SWITCHABLE}


async def enabled(s: AsyncSession, names: Iterable[str]) -> list[str]:
    cur = await current(s)
    return [n for n in names if n in cur and cur[n]["enabled"]]


async def disabled(s: AsyncSession, names: Iterable[str]) -> set[str]:
    cur = await current(s)
    return {n for n in names if n in cur and not cur[n]["enabled"]}


async def history(s: AsyncSession, limit: int = 100) -> list[dict[str, Any]]:
    rows = (await s.execute(text("""select strategy, enabled, reason, created_at
        from strategy_switch order by id desc limit :n"""), {"n": limit})).all()
    return [{"strategy": r.strategy, "enabled": r.enabled, "reason": r.reason,
             "at": r.created_at} for r in rows]


async def set_switch(s: AsyncSession, strategy: str, on: bool, reason: str,
                     token: str | None) -> dict[str, Any]:
    fp = authorize_write(token)
    if strategy not in RG.SWITCHABLE:
        raise SwitchRefused(f"{strategy} cannot be switched (known: {', '.join(RG.SWITCHABLE)})")
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise SwitchRefused("a reason is required")
    cur = (await current(s))[strategy]
    if cur["enabled"] == on:
        return {"strategy": strategy, "enabled": on, "status": "UNCHANGED"}
    await s.execute(text("""insert into strategy_switch (strategy, enabled, reason,
        authz_token_sha256) values (:s, :e, :r, :a)"""),
        {"s": strategy, "e": on, "r": reason[:500], "a": fp})
    await s.commit()
    meta = RG.BY_NAME[strategy]
    return {"strategy": strategy, "enabled": on, "status": "CHANGED",
            "warning": (f"{strategy} is in a frozen forward test ({meta.look}); switching it "
                        "off stops its record and is logged as a protocol deviation")
            if (not on and meta.look) else None}
