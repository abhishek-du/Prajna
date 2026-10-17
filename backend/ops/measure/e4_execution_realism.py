"""E4 gap fade: how far a real entry/exit sits from the official open/close (READ ONLY).

The single E4 look (docs/STAGE4_E4_RESULTS.md) bought at the official open and sold at the
official close; the edge is gone at 10-20 bps of slippage per side. This measures the
price distance a live MIS trade would actually face, for the gap-fade picks (arm P, from
the recorded paper target lists) on the sessions with pre-open and 1m data:

  entry   iep_0907   last indicative equilibrium price before the 09:08 order cut-off
          m1_0915_c  close of the 09:15 1m bar (a market order right after the open)
          vwap_0915_19  volume-weighted price of 09:15-09:19 (an order spread over 5 min)
  exit    m1_1515_c / m1_1520_c  1m closes (broker MIS square-off happens ~15:15-15:20),
          against the official close (NSE: the 15:00-15:30 VWAP)
  buy-side cost in bps: (entry / open - 1) x 1e4; sell-side: (1 - exit / close) x 1e4

Selection drift: live, the pick must be made on the 09:07 IEP, not the official open. The
top-K down-gaps by IEP are compared with the top-K by open (overlap), and - ONLY on
sessions after the E4 TEST window (from 2026-10-01) - the open->close gross of the two lists.
TEST-window sessions are used for price distances (a cost measurement) only; no return of
a TEST session is computed here (the E4 look is spent).

  .venv/bin/python ops/measure/e4_execution_realism.py [--out FILE]
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import json
import pathlib
import sys
from statistics import mean, median

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from app.core.clock import IST, now  # noqa: E402
from app.db.engine import get_sessionmaker  # noqa: E402
from app.paper import strategies as ST  # noqa: E402
from app.training import e4 as E4  # noqa: E402

AFTER_TEST = _dt.date(2026, 10, 1)


def pct(v: list[float], q: float) -> float | None:
    if not v:
        return None
    s = sorted(v)
    return s[min(len(s) - 1, int(q * (len(s) - 1) + 0.5))]


def stats(v: list[float]) -> dict:
    v = [x for x in v if x is not None]
    return {"n": len(v), "mean_bps": round(mean(v), 2) if v else None,
            "median_bps": round(median(v), 2) if v else None,
            "p75_bps": round(pct(v, 0.75), 2) if v else None,
            "p90_bps": round(pct(v, 0.90), 2) if v else None}


async def main(out: pathlib.Path | None) -> dict:
    async with get_sessionmaker()() as s:
        await s.execute(text("set transaction isolation level repeatable read, read only"))
        runs = (await s.execute(text("""select session_date, target_list from paper_run
            where strategy = 'baseline_gap_fade' order by 1"""))).all()
        sess = [r.session_date for r in runs]
        have = set((await s.execute(text("""select distinct market_date from canon_preopen
            where market_date = any(:d)"""), {"d": sess})).scalars())
        days = [d for d in sess if d in have]
        picks = {r.session_date: [e["key"] for e in r.target_list["entries"]]
                 for r in runs if r.session_date in have}
        m = await ST.load_market(s, days[0], days[-1], cutoff=now())
        rows, sel = [], []
        for d in days:
            di = m.d(d)
            u = E4.eligible(m.series, di, m.suspect)
            ukeys = [r[0] for r in u]
            iep = dict((await s.execute(text("""select distinct on (instrument_key)
                    instrument_key, iep from canon_preopen
                where market_date = :d and instrument_key = any(:k) and iep > 0
                  and (event_ts at time zone 'Asia/Kolkata')::time < '09:08'
                order by instrument_key, event_ts desc"""), {"d": d, "k": ukeys})).all())
            bars = (await s.execute(text("""select instrument_key,
                    to_char(bar_start_utc at time zone 'Asia/Kolkata', 'HH24:MI') hm,
                    open, high, low, close, volume from canon_market_bar
                where timeframe = '1m' and market_date = :d and instrument_key = any(:k)
                  and ((bar_start_utc at time zone 'Asia/Kolkata')::time between '09:15' and '09:19'
                    or (bar_start_utc at time zone 'Asia/Kolkata')::time in ('15:15', '15:20'))"""),
                {"d": d, "k": picks[d]})).all()
            m1: dict[str, dict] = {}
            for b in bars:
                m1.setdefault(b.instrument_key, {})[b.hm] = b
            for k in picks[d]:
                ser = m.series[k]
                o, c = ser["open"][di], ser["close"][di]
                if not o or not c:
                    continue
                row = {"d": str(d), "key": k}
                if k in iep:
                    row["iep_0907"] = (float(iep[k]) / o - 1) * 1e4
                b = m1.get(k, {})
                if "09:15" in b and b["09:15"].close:
                    row["m1_0915_c"] = (float(b["09:15"].close) / o - 1) * 1e4
                vw = [(float((x.high + x.low + x.close) / 3), float(x.volume or 0))
                      for hm, x in b.items() if "09:15" <= hm <= "09:19"]
                if vw and sum(v for _, v in vw) > 0:
                    row["vwap_0915_19"] = (sum(p * v for p, v in vw) / sum(v for _, v in vw)
                                           / o - 1) * 1e4
                for hm, name in (("15:15", "m1_1515_c"), ("15:20", "m1_1520_c")):
                    if hm in b and b[hm].close:
                        row[name] = (1 - float(b[hm].close) / c) * 1e4
                rows.append(row)
            # selection on the 09:07 IEP vs on the official open
            pc = {k: m.series[k]["close"][di - 1] for k in ukeys}
            by_iep = sorted((k for k in ukeys if k in iep and pc[k]),
                            key=lambda k: (float(iep[k]) / pc[k] - 1, k))[:E4.K]
            by_open = picks[d]
            ov = len(set(by_iep) & set(by_open))
            rec = {"d": str(d), "overlap": ov, "k": len(by_open), "iep_known": len(iep),
                   "universe": len(ukeys)}
            if d >= AFTER_TEST:
                def oc(keys):
                    r = [E4.oc_return(m.series[k], di) for k in keys]
                    r = [x for x in r if x is not None]
                    return round(mean(r) * 1e4, 2) if r else None
                rec.update(gross_by_open_bps=oc(by_open), gross_by_iep_bps=oc(by_iep))
            sel.append(rec)
        await s.rollback()
    res = {"generated_at": now().astimezone(IST).isoformat(), "sessions": [str(d) for d in days],
           "picks": len(rows),
           "entry_buy_cost_vs_open": {f: stats([r.get(f) for r in rows])
                                      for f in ("iep_0907", "m1_0915_c", "vwap_0915_19")},
           "exit_sell_cost_vs_close": {f: stats([r.get(f) for r in rows])
                                       for f in ("m1_1515_c", "m1_1520_c")},
           "selection": {"mean_overlap_of_10": round(mean(x["overlap"] for x in sel), 2),
                         "by_session": sel},
           "note": "bps; positive = worse than the official price. Returns only for sessions "
                   ">= 2026-10-01 (after the E4 TEST window)."}
    body = json.dumps(res, indent=1, default=str)
    if out:
        out.write_text(body)
    print(body)
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=pathlib.Path)
    asyncio.run(main(ap.parse_args().out))
