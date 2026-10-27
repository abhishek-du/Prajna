"""The nightly Strategy Lab Telegram text: the latest session's per-strategy result (real
trades only), equity, drawdown, best and worst name, and a drawdown alert. Read-only.

    .venv/bin/python -m app.lab.summary
"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import text

from app.lab import registry as RG

DD_ALERT = 0.05


async def latest(s) -> tuple[Any, list[Any]]:
    day = (await s.execute(text("""select max(session_date) from lab_run
        where kind = 'DAILY'"""))).scalar()
    if day is None:
        return None, []
    rows = (await s.execute(text("""select distinct on (d.strategy) d.* from strategy_day d
        join lab_run r using (run_id) where d.session_date = :d
        order by d.strategy, r.created_at desc"""), {"d": day})).mappings().all()
    order = {x.name: i for i, x in enumerate(RG.STRATEGIES)}
    return day, sorted(rows, key=lambda r: order.get(r["strategy"], 99))


def render(day, rows) -> str:
    if day is None:
        return ""
    lines = [f"Prajna Strategy Lab {day} (paper/shadow; not advice)"]
    alerts = []
    for r in rows:
        meta = RG.BY_NAME.get(r["strategy"])
        name = r["strategy"]
        if r["enabled"] is False:
            lines.append(f"- {name}: OFF")
            continue
        det = r["detail"] or {}
        extra = f" best {det['best']}, worst {det['worst']}" if r["trades"] else ""
        lines.append(f"- {name}: {r['trades']} trades, {r['wins']} won, net "
                     f"Rs {float(r['net_inr']):,.0f}; equity Rs {float(r['equity_inr']):,.0f}, "
                     f"DD {r['drawdown']:.1%}.{extra}")
        if r["drawdown"] >= DD_ALERT and meta and meta.family != "E6":
            alerts.append(f"{name} drawdown {r['drawdown']:.1%}")
    if rows and rows[0]["regime_pre"]:
        lines.insert(1, f"Regime: {rows[0]['regime_pre']} / open {rows[0]['regime_open']} / "
                        f"day {rows[0]['day_type']}")
    if alerts:
        lines.append("ALERT: " + "; ".join(alerts))
    lines.append("Details: dashboard http://127.0.0.1:8600/#/lab")
    return "\n".join(lines)


async def _main() -> str:
    from app.db.engine import get_sessionmaker
    async with get_sessionmaker()() as s:
        day, rows = await latest(s)
        await s.rollback()
    return render(day, rows)


if __name__ == "__main__":
    print(asyncio.run(_main()))
