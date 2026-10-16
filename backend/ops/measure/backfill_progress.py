"""Stage 1 intraday backfill progress per timeframe (READ ONLY). Used by the hourly
Telegram update (ops/runbooks/backfill_supervisor.sh hourly).

  .venv/bin/python ops/measure/backfill_progress.py

Per timeframe: instruments whose stream checkpoint reaches the approved depth (1h and 15m
since 2022-01-01, 1m for the last 92 days), the historical runs and bars of the last hour,
and an ETA at that pace.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from app.db.engine import get_sessionmaker  # noqa: E402
from app.ingest import backfill_progress as BP  # noqa: E402


async def progress() -> list[str]:
    async with get_sessionmaker()() as s:
        await s.execute(text("set transaction isolation level repeatable read, read only"))
        out = [BP.line(r) for r in await BP.rows(s)]
        await s.rollback()
    return out


if __name__ == "__main__":
    print("\n".join(asyncio.run(progress())))
