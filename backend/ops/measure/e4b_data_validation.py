"""E4b step 2: OUTCOME-BLIND data validation (pre-registration docs/STAGE4_E4B_PREREGISTRATION_
DRAFT.md section 9, approved 2026-10-19). READ ONLY on the database; writes one file.

  .venv/bin/python ops/measure/e4b_data_validation.py [--jobs 12]

Reads ONLY bar presence (which 15m / 1h slots exist per name and session) and the open of
the 09:15 15m bar; never a close, high, low or volume of an intraday bar, so no return,
score or pick is computed. The daily universe is e4.eligible on the frozen E4 daily
dataset (the same arrays and suspect rule as the E4a look).

Reports, on the TEST window 2022-01-03 .. 2026-09-30:
  sessions   regular (NIFTY 50 has all 25 15m bars) vs special, listed
  coverage   eligible names with any 15m / 1h bar, per year
  missing    per-slot presence rates (15m 25 slots, 1h 7) among eligible names on regular
             sessions; entry bars (15m 09:30, 1h 10:15) and exit bars (15:15)
  open       |09:15 15m open / official open - 1| > 1 % (the data-error mask) and its
             distribution
  universe   per session and hypothesis, after the open mask and the signal bar; the
             expected names per control cell (universe / 45)
The unmatched-control rate needs the picks, so it is reported by the look, not here.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import json
import pathlib
import sys
from concurrent.futures import ProcessPoolExecutor
from typing import Any

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from app.core.clock import IST, now  # noqa: E402
from app.db.engine import get_sessionmaker  # noqa: E402
from app.training import e3 as E3  # noqa: E402
from app.training import e4 as E4  # noqa: E402
from app.training import e4b as X  # noqa: E402

TEST = (_dt.date(2022, 1, 3), _dt.date(2026, 9, 30))
INDEX_KEY = "NSE_INDEX|Nifty 50"
OUT = ROOT / "var/stage4/experiments/e4b"
BATCH = 50
SLOT_SQL = """select instrument_id, session_date,
    bit_or(1::bigint << ((extract(epoch from (bar_start_utc at time zone 'Asia/Kolkata')::time)
                          - 33300)::int / :w)) filter (where
        extract(epoch from (bar_start_utc at time zone 'Asia/Kolkata')::time) >= 33300) as m,
    max(open) filter (where (bar_start_utc at time zone 'Asia/Kolkata')::time = '09:15') as o0
  from ohlcv_bar
 where instrument_id = any(:ids) and timeframe = :tf and session_date between :a and :b
 group by 1, 2"""


def load_daily():
    spec = __import__("importlib.util").util.spec_from_file_location(
        "e4_test_look", ROOT / "ops/measure/e4_test_look.py")
    look = __import__("importlib.util").util.module_from_spec(spec)
    spec.loader.exec_module(look)
    return look.load()                       # refuses unless the frozen content sha matches


async def load_intraday(keys: list[str], days: list[_dt.date]) -> dict[str, Any]:
    di = {d: i for i, d in enumerate(days)}
    n, m = len(keys), len(days)
    out = {"m15": np.zeros((n, m), np.int64), "h1": np.zeros((n, m), np.int64),
           "o0": np.full((n, m), np.nan)}
    async with get_sessionmaker()() as s:
        await s.execute(text("set transaction isolation level repeatable read, read only"))
        ids = dict((await s.execute(text("""select instrument_key, instrument_id from instrument
            where valid_to = 'infinity' and instrument_key = any(:k)"""),
            {"k": [*keys, INDEX_KEY]})).all())
        row_of = {ids[k]: j for j, k in enumerate(keys) if k in ids}
        idx = {"m15": np.zeros(m, np.int64)}
        all_ids = sorted(row_of)
        for tf, w, name in (("15m", 900, "m15"), ("1h", 3600, "h1")):
            for b in range(0, len(all_ids), BATCH):
                rows = (await s.execute(text(SLOT_SQL), {
                    "ids": all_ids[b:b + BATCH], "tf": tf, "w": w, "a": days[0],
                    "b": days[-1]})).all()
                for iid, sd, mask, o0 in rows:
                    i = di.get(sd)
                    if i is None:
                        continue
                    out[name][row_of[iid], i] = mask or 0
                    if name == "m15" and o0 is not None:
                        out["o0"][row_of[iid], i] = float(o0)
            print(f"[{now().astimezone(IST):%H:%M:%S}] loaded {tf}", flush=True)
        for _iid, sd, mask, _ in (await s.execute(text(SLOT_SQL), {
                "ids": [ids[INDEX_KEY]], "tf": "15m", "w": 900, "a": days[0],
                "b": days[-1]})).all():
            if sd in di:
                idx["m15"][di[sd]] = mask or 0
        await s.rollback()
    out["index_m15"] = idx["m15"]
    out["missing_ids"] = [k for k in keys if k not in ids]
    return out


_S: dict[str, Any] = {}


def _init(series, suspect):
    _S["series"], _S["suspect"] = series, suspect


def _eligible(d: int) -> list[str]:
    return [r[0] for r in E4.eligible(_S["series"], d, _S["suspect"])]


def has(mask: int, slot: int) -> bool:
    return bool((int(mask) >> slot) & 1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=12)
    a = ap.parse_args()
    days, series = load_daily()
    keys = list(series)
    test_idx = [i for i, d in enumerate(days) if TEST[0] <= d <= TEST[1]]
    intra = asyncio.run(load_intraday(keys, days))
    full = (1 << X.M15_SLOTS) - 1
    regular = [int(intra["index_m15"][i]) & full == full for i in range(len(days))]
    suspect = {k: E3.suspect_sessions(s) for k, s in series.items()}
    with ProcessPoolExecutor(a.jobs, initializer=_init, initargs=(series, suspect)) as ex:
        elig = dict(zip(test_idx, ex.map(_eligible, test_idx, chunksize=8), strict=True))
    print(f"[{now().astimezone(IST):%H:%M:%S}] universe done", flush=True)
    row = {k: j for j, k in enumerate(keys)}

    special = [str(days[i]) for i in test_idx if not regular[i]]
    slots15, slots1h = np.zeros(X.M15_SLOTS), np.zeros(X.H1_SLOTS)
    n_pairs, dev, by_year, per_session = 0, [], {}, []
    for i in test_idx:
        if not regular[i]:
            continue
        y = days[i].year
        yb = by_year.setdefault(y, {"pairs": 0, "any_15m": 0, "any_1h": 0, "open_bad": 0,
                                    "open_missing": 0})
        u = {"B1": 0, "B2": 0, "B3": 0}
        for k in elig[i]:
            j = row[k]
            m15, h1 = int(intra["m15"][j, i]), int(intra["h1"][j, i])
            n_pairs += 1
            yb["pairs"] += 1
            yb["any_15m"] += m15 != 0
            yb["any_1h"] += h1 != 0
            slots15 += [(m15 >> s) & 1 for s in range(X.M15_SLOTS)]
            slots1h += [(h1 >> s) & 1 for s in range(X.H1_SLOTS)]
            o0, od = intra["o0"][j, i], series[k]["open"][i]
            if not np.isfinite(o0) or not od:
                yb["open_missing"] += 1
                continue
            r = abs(o0 / od - 1)
            dev.append(r)
            if r > X.OPEN_TOL:
                yb["open_bad"] += 1
                continue
            u["B1"] += 1                                  # the 09:15 15m bar exists
            u["B3"] += 1
            u["B2"] += has(h1, 0)
        per_session.append({"d": str(days[i]), "eligible": len(elig[i]), **u})
    dev_a = np.array(dev)
    uni = {h: [s[h] for s in per_session] for h in ("B1", "B2", "B3")}
    res = {
        "generated_at": now().isoformat(), "test": [str(d) for d in TEST],
        "outcome_blind": "bar presence and the 09:15 15m open only; no return, score or pick",
        "sessions": {"test": len(test_idx), "regular": len(test_idx) - len(special),
                     "special": special},
        "eligible_pairs_regular": n_pairs,
        "keys_without_instrument": len(intra["missing_ids"]),
        "by_year": by_year,
        "presence_15m_by_slot": {f"{9 + (15 + 15 * s) // 60:02d}:{(15 + 15 * s) % 60:02d}":
                                 round(float(v / max(n_pairs, 1)), 4)
                                 for s, v in enumerate(slots15)},
        "presence_1h_by_slot": {f"{9 + s + 0:02d}:15": round(float(v / max(n_pairs, 1)), 4)
                                for s, v in enumerate(slots1h)},
        "open_deviation": {"n": len(dev), "over_1pct": int((dev_a > X.OPEN_TOL).sum()),
                           "share_over_1pct": (float((dev_a > X.OPEN_TOL).mean())
                                               if len(dev) else None),
                           "p50": float(np.quantile(dev_a, .5)) if len(dev) else None,
                           "p99": float(np.quantile(dev_a, .99)) if len(dev) else None,
                           "exact_share": float((dev_a == 0).mean()) if len(dev) else None},
        "universe": {h: {"min": int(min(v)), "p10": float(np.quantile(v, .1)),
                         "median": float(np.median(v)), "per_control_cell_median":
                         float(np.median(v)) / 45} for h, v in uni.items() if v},
        "per_session": per_session,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    f = OUT / f"data_validation_{now().astimezone(IST):%Y%m%dT%H%M}.json"
    f.write_text(json.dumps(res, indent=1, sort_keys=True, default=str))
    print(json.dumps({k: v for k, v in res.items() if k != "per_session"}, indent=1,
                     default=str))
    print(f"wrote {f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
