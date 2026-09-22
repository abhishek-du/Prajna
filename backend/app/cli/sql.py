"""Ad-hoc SQL for inspection. READ-ONLY unless explicitly overridden.

There is no psql client on this host, so this is the query surface. It opens a
read-only transaction by default, which means a typo cannot damage anything:
Postgres itself rejects the write, not a regex we hoped was complete.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

from sqlalchemy import text

from app.db.engine import get_engine


def _fmt(v) -> str:
    if v is None:
        return "·"
    if isinstance(v, Decimal):
        return f"{v:g}"
    s = str(v)
    return s if len(s) <= 60 else s[:57] + "..."


async def run_sql(statement: str, *, allow_write: bool = False, limit: int = 100) -> None:
    engine = get_engine()
    async with engine.connect() as conn:
        if not allow_write:
            # Enforced by the server, not by string matching.
            await conn.execute(text("SET TRANSACTION READ ONLY"))
        try:
            res = await conn.execute(text(statement))
        except Exception as e:
            print(f"ERROR: {type(e).__name__}: {str(e).splitlines()[0]}")
            await engine.dispose()
            raise SystemExit(1) from None

        if not res.returns_rows:
            print(f"OK ({res.rowcount} row(s) affected)")
        else:
            rows = res.fetchmany(limit)
            cols = list(res.keys())
            widths = [
                max(len(c), *(len(_fmt(r[i])) for r in rows)) if rows else len(c)
                for i, c in enumerate(cols)
            ]
            print("  ".join(c.ljust(w) for c, w in zip(cols, widths)))
            print("  ".join("-" * w for w in widths))
            for r in rows:
                print("  ".join(_fmt(r[i]).ljust(w) for i, w in enumerate(widths)))
            more = " (truncated)" if len(rows) == limit else ""
            print(f"\n{len(rows)} row(s){more}")
        if allow_write:
            await conn.commit()
    await engine.dispose()


def main(statement: str, allow_write: bool, limit: int) -> None:
    asyncio.run(run_sql(statement, allow_write=allow_write, limit=limit))
