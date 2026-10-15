"""Stage 1 intraday backfill progress per timeframe (READ ONLY). Used by the hourly
Telegram update (ops/runbooks/backfill_supervisor.sh hourly).

  .venv/bin/python ops/measure/backfill_progress.py

Per timeframe: instruments whose stream checkpoint reaches the approved depth (1h and 15m
since 2022-01-01, 1m for the last 92 days), the historical runs and bars of the last hour,
and an ETA at that pace.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from app.db.engine import get_sessionmaker  # noqa: E402

DEPTH = {"1h": _dt.date(2022, 1, 1), "15m": _dt.date(2022, 1, 1),
         "1m": _dt.date.today() - _dt.timedelta(days=92)}
UNIVERSE = "i.valid_to = 'infinity' and i.segment in ('NSE_EQ', 'NSE_INDEX')"


def eta(done: int, total: int, per_hour: int) -> str:
    if done >= total:
        return "done"
    if not per_hour:
        return "not running"
    return f"~{(total - done) / per_hour:.1f} h at this pace"


async def progress() -> list[str]:
    async with get_sessionmaker()() as s:
        await s.execute(text("set transaction isolation level repeatable read, read only"))
        q_total = f"select count(*) from instrument i where {UNIVERSE}"  # noqa: S608
        total = (await s.execute(text(q_total))).scalar()
        out = []
        for tf, depth in DEPTH.items():
            done = (await s.execute(text(f"""select count(*) from instrument i
                join ingest_watermark w on w.source = 'UPSTOX_REST_V3'
                 and w.stream = 'ohlcv.' || :tf || '.' || i.instrument_key
                join ingest_run r on r.run_id = w.last_run_id
                where {UNIVERSE}
                  and (r.request_params -> 'outcome' -> 'checkpoint'
                       ->> 'covered_from')::date <= :d"""),  # noqa: S608
                {"tf": tf, "d": depth})).scalar()
            runs, bars = (await s.execute(text("""select count(*), coalesce(sum(rows_written), 0)
                from ingest_run where stream like 'ohlcv.' || :tf || '.%'
                  and status = 'COMPLETE' and started_at > now() - interval '1 hour'
                  and request_params ->> 'endpoint' = 'historical'"""), {"tf": tf})).one()
            pct = 100.0 * done / total if total else 0.0
            out.append(f"{tf}: {done}/{total} instruments ({pct:.1f}%), last hour {runs} runs / "
                       f"{int(bars):,} bars, ETA {eta(done, total, runs)}")
        await s.rollback()
    return out


if __name__ == "__main__":
    print("\n".join(asyncio.run(progress())))
