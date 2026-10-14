"""E2 PC-4: the opening half-spread, measured from every captured pre-open session
(READ ONLY: repeatable read, read only transaction). Writes a frozen JSON under
var/stage4/costs/ that the E2 configuration references by sha256.

  .venv/bin/python ops/measure/e2_open_spread.py [--through 2026-10-14]

Per session D (every date with pre-open capture, up to --through):
  universe  the top 500 by turnover_20 among names with all 24 E1/E2 core features
            VALID at D's PRE_SESSION snapshot: production feature_value when D has it,
            else the stage4-ds-v3-strict training snapshot (source recorded per date)
  quotes    rung-0 book of every tick with 09:15:00 <= vendor_ts < 09:20:00 IST and
            0 < bid <= ask; half-spread bps = (ask - bid) / (ask + bid) * 10,000
  per name  median half-spread over its quotes; RELIABLE when it has >= MIN_QUOTES
            quotes; first_quote = the half-spread of its earliest quote
Proxy (the C3 fallback) = median over every reliable (date, name) of the per-name
median; the first-quote median is the pessimistic sensitivity. The per (date, name)
reliable values are kept: they are the measured spreads for sessions that have them.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import hashlib
import json
import pathlib
import statistics
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from app.core.clock import IST, now  # noqa: E402
from app.db.engine import get_sessionmaker  # noqa: E402
from app.training import e1 as E  # noqa: E402

OUT = ROOT / "var/stage4/costs"
TOP, MIN_QUOTES = 500, 3

UNIVERSE = {
    "production": """select instrument_key from feature_value
        where session_date = :d and snapshot = 'PRE_SESSION' and feature_id = any(:ids)
        group by 1 having count(*) filter (where value is not null) = :n
        order by max(value) filter (where feature_id = 'turnover_20') desc, 1 limit :top""",
    "stage4-ds-v3-strict": """select instrument_key from training_feature_value
        where dataset_version = 'stage4-ds-v3-strict' and session_date = :d
          and snapshot = 'PRE_SESSION' and feature_id = any(:ids) and status = 'VALID'
        group by 1 having count(*) = :n
        order by max(value) filter (where feature_id = 'turnover_20') desc, 1 limit :top"""}

QUOTES = """select t.instrument_key, t.vendor_ts, b.bid_price, b.ask_price
    from preopen_tick t join preopen_book b on b.tick_id = t.tick_id and b.rung_no = 0
    where t.session_date = :d and t.instrument_key = any(:keys)
      and t.vendor_ts >= :a and t.vendor_ts < :b
      and b.bid_price > 0 and b.ask_price >= b.bid_price
    order by t.instrument_key, t.vendor_ts"""


async def measure(through: _dt.date) -> dict:
    ids, n = list(E.CORE24), len(E.CORE24)
    async with get_sessionmaker()() as s:
        await s.execute(text("set transaction isolation level repeatable read, read only"))
        dates = list((await s.execute(text("""select distinct session_date from preopen_tick
            where session_date <= :t order by 1"""), {"t": through})).scalars())
        per_date, measured = {}, {}
        for d in dates:
            keys, src = [], None
            for name, sql in UNIVERSE.items():
                keys = list((await s.execute(text(sql), {"d": d, "ids": ids, "n": n,
                                                         "top": TOP})).scalars())
                if keys:
                    src = name
                    break
            a = _dt.datetime.combine(d, _dt.time(9, 15), IST)
            b = _dt.datetime.combine(d, _dt.time(9, 20), IST)
            q: dict[str, list[float]] = {}
            for k, _ts, bid, ask in (await s.execute(text(QUOTES), {
                    "d": d, "keys": keys, "a": a, "b": b})).all():
                q.setdefault(k, []).append(float((ask - bid) / (ask + bid)) * 10_000)
            rel = {k: v for k, v in q.items() if len(v) >= MIN_QUOTES}
            meds = {k: statistics.median(v) for k, v in rel.items()}
            measured[str(d)] = {k: round(v, 4) for k, v in sorted(meds.items())}
            per_date[str(d)] = {
                "universe_source": src, "universe": len(keys), "quoted": len(q),
                "reliable": len(rel),
                "median_half_spread_bps": statistics.median(meds.values()) if meds else None,
                "first_quote_median_bps": statistics.median(v[0] for v in rel.values())
                if rel else None}
        await s.rollback()
    allm = [v for d in measured.values() for v in d.values()]
    first = [per_date[d]["first_quote_median_bps"] for d in per_date
             if per_date[d]["first_quote_median_bps"] is not None]
    return {
        "measure": "E2 opening half-spread (PC-4)", "through": str(through),
        "method": __doc__.split("Per session D")[1].strip(),
        "min_quotes": MIN_QUOTES, "universe_top": TOP, "sessions": len(dates),
        "sessions_used": sum(1 for v in per_date.values() if v["reliable"]),
        "reliable_name_days": len(allm),
        "proxy_half_spread_bps": round(statistics.median(allm), 4) if allm else None,
        "proxy_quantiles_bps": {str(p): round(statistics.quantiles(allm, n=100)[p - 1], 4)
                                for p in (10, 25, 75, 90)} if len(allm) > 100 else None,
        "first_quote_sensitivity_bps": round(statistics.median(first), 4) if first else None,
        "per_date": per_date, "measured_half_spread_bps": measured}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--through", type=_dt.date.fromisoformat,
                    default=now().astimezone(IST).date())
    a = ap.parse_args()
    out = asyncio.run(measure(a.through))
    out["at"] = now().astimezone(IST).isoformat()
    body = json.dumps(out, indent=1, sort_keys=True)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"open_spread_through_{a.through}.json"
    if path.exists():
        raise SystemExit(f"REFUSED: {path.name} exists (frozen); not overwritten")
    path.write_text(body)
    print(json.dumps({"written": str(path),
                      "sha256": hashlib.sha256(body.encode()).hexdigest(),
                      **{k: out[k] for k in ("sessions", "sessions_used", "reliable_name_days",
                                             "proxy_half_spread_bps", "proxy_quantiles_bps",
                                             "first_quote_sensitivity_bps")},
                      "per_date": {d: {k: v[k] for k in ("universe_source", "reliable",
                                                         "median_half_spread_bps")}
                                   for d, v in out["per_date"].items()}}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
