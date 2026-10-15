"""Daily corporate-action refresh D1: which ISINs to sweep (READ ONLY). Used by
ops/runbooks/ca_refresh.sh (docs/STAGE1_DAILY_CA_REFRESH_PLAN.md, approved 2026-10-15).

  .venv/bin/python ops/measure/ca_targets.py targeted   # 06:45: (a) announcements + (b) failures
  .venv/bin/python ops/measure/ca_targets.py rolling    # after the close: 1/5 of all ISINs
  .venv/bin/python ops/measure/ca_targets.py selfheal   # after the morning: today's D3 failures

Prints one JSON object: {"mode", "isins", "keys", "reasons"}.

(a) NSE_ANNOUNCEMENTS of the last 60 days that name a bonus, a split / sub-division or a
    share consolidation (a dividend-only record date is not a price-basis event), mapped
    to a current NSE_EQ ISIN by trading symbol or by company name.
(b) every current NSE_EQ key whose latest 1D run in the last 3 days FAILED with
    DUPLICATE_KEY (the D3 UNEXPLAINED signature of MOLDTEK / OLIL).
rolling: the ISINs whose sha256 bucket (mod 5) is today's weekday (Mon=0 .. Fri=4), so
    every ISIN is swept at least once a week besides the Saturday full sweep.
selfheal: (b) restricted to runs started today (IST).
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import hashlib
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from app.core.clock import IST, now  # noqa: E402
from app.db.engine import get_sessionmaker  # noqa: E402

EVENT = re.compile(r"\b(bonus|stock split|split|sub-?division|consolidation of (equity )?shares)\b",
                   re.IGNORECASE)
CURRENT_EQ = "i.valid_to = 'infinity' and i.segment = 'NSE_EQ' and i.isin is not null"
BUCKETS = 5


def is_ca_event(*parts: str | None) -> bool:
    """A bonus / split / sub-division / share consolidation announcement."""
    return bool(EVENT.search(" ".join(p for p in parts if p)))


def bucket(isin: str) -> int:
    return int(hashlib.sha256(isin.encode()).hexdigest(), 16) % BUCKETS


async def _announced(s) -> dict[str, str]:
    rows = (await s.execute(text(f"""
        select distinct on (n.id) i.isin, n.symbol_raw, n.category_raw, n.title, n.summary
          from news_item n
          join instrument i on {CURRENT_EQ}
           and (i.trading_symbol = n.symbol_raw or upper(i.name) = upper(n.title))
         where n.source = 'NSE_ANNOUNCEMENTS'
           and n.published_at > now() - interval '60 days'"""))).all()  # noqa: S608
    return {r.isin: f"announcement:{r.category_raw or '-'}" for r in rows
            if is_ca_event(r.category_raw, r.title, r.summary)}


async def _failed(s, since: _dt.datetime) -> dict[str, str]:
    rows = (await s.execute(text(f"""
        select i.isin, i.instrument_key from instrument i
          join lateral (select status, error from ingest_run r
                         where r.stream = 'ohlcv.1d.' || i.instrument_key
                           and r.started_at >= :since
                         order by r.started_at desc limit 1) r on true
         where {CURRENT_EQ} and r.status = 'FAILED' and r.error like '%DUPLICATE_KEY%'"""),  # noqa: S608
        {"since": since})).all()
    return {r.isin: f"d3_failure:{r.instrument_key}" for r in rows}


async def targets(mode: str) -> dict:
    t = now().astimezone(IST)
    async with get_sessionmaker()() as s:
        await s.execute(text("set transaction isolation level repeatable read, read only"))
        if mode == "targeted":
            reasons = {**await _announced(s), **await _failed(s, t - _dt.timedelta(days=3))}
        elif mode == "selfheal":
            midnight = t.replace(hour=0, minute=0, second=0, microsecond=0)
            reasons = await _failed(s, midnight)
        elif mode == "rolling":
            day = t.weekday()
            isins = (await s.execute(text(
                f"select distinct i.isin from instrument i where {CURRENT_EQ}"  # noqa: S608
            ))).scalars()
            reasons = {x: f"rolling:{day}" for x in isins if bucket(x) == day} if day < 5 else {}
        else:
            raise SystemExit(f"unknown mode {mode}")
        await s.rollback()
    isins = sorted(reasons)
    keys = [f"NSE_EQ|{x}" for x in isins]
    return {"mode": mode, "isins": isins, "keys": keys, "reasons": reasons}


if __name__ == "__main__":
    print(json.dumps(asyncio.run(targets(sys.argv[1] if len(sys.argv) > 1 else "targeted"))))
