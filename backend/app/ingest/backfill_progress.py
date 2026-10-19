"""Stage 1 intraday backfill progress per timeframe, from the database (READ ONLY).

Shared by ops/measure/backfill_progress.py (the hourly Telegram text) and the dashboard
API, so both report the same numbers.

Per timeframe:
  covered   instruments whose stream checkpoint covers the approved depth (1h and 15m
            since 2022-01-01, 1m for the last 92 days) through the last session (3 days
            of lag allowed) - the rule of Stage 1 criterion F (acceptance/stage1.py)
  total     current ACTIVE NSE_EQ/NSE_INDEX instruments: the universe backfill.sh fetches.
            Instruments REMOVED_FROM_MASTER are not served by the vendor any more and are
            never fetched; counting them made 1h stop at 3579/3585 (fixed 2026-10-19)
  done_1h   instruments that reached the depth in the last hour (the pace)
  runs_1h, bars_1h   historical runs completed in the last hour
  eta_hours remaining / done_1h; None when nothing completed in the last hour
A run's window count differs by timeframe (a quarter per 1h request, a month per 15m
request), so the pace is counted in instruments, never in runs (fixed 2026-10-16: the
earlier ETA divided instruments by runs and was ~19x too optimistic).
"""

from __future__ import annotations

import datetime as _dt
import math
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

INTRADAY_FROM = _dt.date(2022, 1, 1)
M1_DAYS = 92
UNIVERSE = ("i.valid_to = 'infinity' and i.segment in ('NSE_EQ', 'NSE_INDEX') "
            "and i.lifecycle_status = 'ACTIVE'")
LAG = _dt.timedelta(days=3)


def depths(today: _dt.date | None = None) -> dict[str, _dt.date]:
    today = today or _dt.date.today()
    return {"1h": INTRADAY_FROM, "15m": INTRADAY_FROM, "1m": today - _dt.timedelta(days=M1_DAYS)}


async def rows(s: AsyncSession, today: _dt.date | None = None) -> list[dict[str, Any]]:
    total = (await s.execute(text(
        f"select count(*) from instrument i where {UNIVERSE}"))).scalar() or 0  # noqa: S608
    last = (await s.execute(text("select max(session_date) from trading_session "
                                 "where is_trading_day and session_date < :t"),
                            {"t": today or _dt.date.today()})).scalar()
    through = (last - LAG) if last else _dt.date.min
    out = []
    for tf, depth in depths(today).items():
        done, done_1h = (await s.execute(text(f"""
            select count(*),
                   count(*) filter (where r.finished_at > now() - interval '1 hour')
            from instrument i
            join ingest_watermark w on w.source = 'UPSTOX_REST_V3'
             and w.stream = 'ohlcv.' || :tf || '.' || i.instrument_key
            join ingest_run r on r.run_id = w.last_run_id
            where {UNIVERSE}
              and (r.request_params -> 'outcome' -> 'checkpoint'
                   ->> 'covered_from')::date <= :d
              and w.last_logical_date >= :through"""),  # noqa: S608
            {"tf": tf, "d": depth, "through": through})).one()
        runs, bars = (await s.execute(text("""select count(*), coalesce(sum(rows_written), 0)
            from ingest_run where stream like 'ohlcv.' || :tf || '.%'
              and status = 'COMPLETE' and started_at > now() - interval '1 hour'
              and request_params ->> 'endpoint' = 'historical'"""), {"tf": tf})).one()
        remaining = max(total - done, 0)
        out.append({"timeframe": tf, "from_date": depth.isoformat(), "covered": int(done),
                    "total": int(total), "pct": (math.floor(10000 * done / total) / 100) if total else None,
                    "done_last_hour": int(done_1h), "runs_last_hour": int(runs),
                    "bars_last_hour": int(bars),
                    "eta_hours": (0.0 if remaining == 0 else
                                  round(remaining / done_1h, 1) if done_1h else None)})
    return out


def line(r: dict[str, Any]) -> str:
    if r["covered"] >= r["total"]:
        eta = "done"
    elif r["eta_hours"] is None:
        eta = "not measurable (nothing completed in the last hour)"
    else:
        eta = f"~{r['eta_hours']:.1f} h at this pace"
    return (f"{r['timeframe']}: {r['covered']}/{r['total']} instruments ({r['pct'] or 0:.2f}%), "
            f"last hour {r['done_last_hour']} instruments / {r['runs_last_hour']} runs / "
            f"{r['bars_last_hour']:,} bars, ETA {eta}")
