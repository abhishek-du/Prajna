"""Verify CA-OBSERVED (features-v3) and F3-PAYLOAD-BASIS (features-v4) on production
data, READ-ONLY (one REPEATABLE READ, READ ONLY transaction; nothing is written).

  1 BLSE (split 1:2, ex 2026-10-06): the 2026-10-05 adjusted close must be 319.15 / 2
    = 159.575 (ADJUSTED); every pre-ex bar adjusted; no jump at the ex-date
  2 BLSE downstream features of the 2026-10-08 PRE_SESSION snapshot recomputed with
    the current registry vs the stored features-v2 values, and vs an independent
    recomputation from the adjusted closes
  3 every instrument with CA_ADJUSTMENT evidence: what F3 changes
  4 the whole 2026-10-08 PRE_SESSION snapshot recomputed vs stored feature_value:
    differences by feature (old / new feature-version behaviour)

  .venv/bin/python ops/measure/ca_fix_verify.py [--out ../audit/evidence/ca_fix_verify.json]
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import json
import pathlib
import sys
from collections import Counter
from decimal import Decimal

from sqlalchemy import text

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from app.canon import pit
from app.core.clock import IST, now
from app.db.engine import get_sessionmaker
from app.features import engine as E
from app.features import registry as R
from app.features import snapshots as SN

BLSE = "NSE_EQ|INE0NLT01028"


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../audit/evidence/ca_fix_verify.json")
    a = ap.parse_args()
    ev: dict = {"generated_at": now().astimezone(IST).isoformat(), "read_only": True,
                "registry": {"version": R.VERSION, "sha256": R.REGISTRY_SHA256}}
    async with get_sessionmaker()() as s:
        await s.execute(text("set transaction isolation level repeatable read, read only"))
        at = now()
        adj = await pit.bars_adjusted(s, BLSE, "1d", at, start=_dt.date(2026, 9, 1))
        rows = {str(r["market_date"]): r for r in adj["rows"]}
        raw = {str(r[0]): Decimal(str(r[1])) for r in (await s.execute(text("""
            select market_date, close from canon_market_bar where instrument_key = :k
              and timeframe = '1d' and market_date >= '2026-09-01' order by 1"""),
            {"k": BLSE})).all()}
        c1005 = rows["2026-10-05"]
        pre = [d for d in rows if d < "2026-10-06"]
        ev["blse_bars"] = {
            "2026-10-05": {"raw_close": str(raw["2026-10-05"]), "adjusted_close": str(c1005["close"]),
                           "status": c1005["adjustment_status"],
                           "factor_applied": str(c1005["factor_applied"])},
            "expected_2026_10_05": "159.575000",
            "pre_ex_all_adjusted": all(rows[d]["adjustment_status"] == "ADJUSTED" for d in pre),
            "jump_at_ex": str(rows["2026-10-06"]["close"] / rows["2026-10-05"]["close"] - 1),
            "refused": adj["refused"]}
        ev["blse_bars"]["pass"] = (str(c1005["close"]) == "159.575000"
                                   and c1005["adjustment_status"] == "ADJUSTED"
                                   and ev["blse_bars"]["pre_ex_all_adjusted"])
        # 2: the 2026-10-08 PRE_SESSION snapshot
        snap = await SN.resolve(s, _dt.date(2026, 10, 8), "PRE_SESSION")
        res = await E.compute_snapshot(s, snap, [BLSE], with_context=False, with_sector=False)
        new = {r.feature_id: r.value for r in res.rows}
        old = {r[0]: (float(r[1]) if r[1] is not None else None, r[2]) for r in (await s.execute(
            text("""select feature_id, value, feature_version from feature_value
                    where instrument_key = :k and session_date = '2026-10-08'
                      and snapshot = 'PRE_SESSION'"""), {"k": BLSE})).all()}
        closes = [rows[d]["close"] for d in sorted(rows) if d < "2026-10-08"]
        indep = {"ret_1d": float(closes[-1] / closes[-2] - 1),
                 "ret_5d": float(closes[-1] / closes[-6] - 1),
                 "ret_20d": float(closes[-1] / closes[-21] - 1) if len(closes) > 20 else None,
                 "sma_20": float(sum(closes[-20:]) / 20) if len(closes) >= 20 else None}
        ev["blse_features_2026_10_08"] = {
            f: {"stored_v2": old.get(f), "recomputed": new.get(f),
                "new_version": R.BY_ID[f].version, "independent": indep.get(f)}
            for f in ("ret_1d", "ret_5d", "ret_20d", "sma_20", "close_to_sma_20",
                      "volatility_20", "atr_pct_14", "rsi_14", "dist_high_20", "breakdown_20")}
        ev["blse_features_2026_10_08_pass"] = all(
            v["independent"] is None or v["recomputed"] is None
            or abs(v["recomputed"] - v["independent"]) <= 1e-9 * max(1, abs(v["independent"]))
            for v in ev["blse_features_2026_10_08"].values())
        # 3: every instrument with CA_ADJUSTMENT evidence
        f3 = []
        for k in (await s.execute(text("""select distinct instrument_key from ohlcv_observation
                where classification = 'CA_ADJUSTMENT' order by 1"""))).scalars():
            r = await pit.bars_adjusted(s, k, "1d", at, start=_dt.date(2026, 9, 1))
            st = Counter(x["adjustment_status"] for x in r["rows"])
            f3.append({"instrument": k, "status": dict(st), "refused": r["refused"]})
        ev["ca_adjustment_instruments"] = f3
        # 4: the whole snapshot vs stored
        keys = list((await s.execute(text("""select distinct instrument_key from feature_value
            where session_date = '2026-10-08' and snapshot = 'PRE_SESSION'
              and instrument_key <> 'MARKET'"""))).scalars())
        full = await E.compute_snapshot(s, snap, keys)
        stored = {(r[0], r[1]): (r[2], r[3], r[4], r[5]) for r in (await s.execute(text("""
            select instrument_key, feature_id, value, reason, inputs_sha256, feature_version
            from feature_value where session_date = '2026-10-08' and snapshot = 'PRE_SESSION'
            """))).all()}
        diff, sha, joined, examples = Counter(), Counter(), 0, []
        for r in full.rows:
            o = stored.get((r.instrument_key, r.feature_id))
            if o is None:
                continue
            joined += 1
            ov = float(o[0]) if o[0] is not None else None
            if ov != r.value or o[1] != r.reason:
                diff[r.feature_id] += 1
                if len(examples) < 25:
                    examples.append([r.instrument_key, r.feature_id, ov, o[1], r.value, r.reason])
            if o[2] != r.inputs_sha256:
                sha[r.feature_id] += 1
        ev["snapshot_2026_10_08_pre_session"] = {
            "rows_joined": joined, "value_or_reason_differences": dict(diff.most_common()),
            "instruments_with_differences": len({e[0] for e in examples}),
            "inputs_sha_differences": dict(sha.most_common()), "examples": examples,
            "stored_registry": "features-v2 (dd696ca6...)", "recomputed_registry": R.VERSION}
        await s.rollback()
    pathlib.Path(a.out).write_text(json.dumps(ev, indent=1, default=str))
    print(json.dumps({k: ev[k] for k in ("registry", "blse_bars", "blse_features_2026_10_08_pass")},
                     indent=1, default=str))
    print(json.dumps(ev["snapshot_2026_10_08_pre_session"]["value_or_reason_differences"]))
    return 0 if ev["blse_bars"]["pass"] and ev["blse_features_2026_10_08_pass"] else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
