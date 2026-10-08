"""label-v1: the outcome of session T for a snapshot taken before T opened.

Both snapshots of T (PRE_SESSION 08:59:59, PRE_OPEN 09:08 IST) precede T's open,
so every label starts at T's open (label_start_at = T open, from the calendar)
and ends at T's close: strictly after the snapshot. A label MAY use future data -
it is the outcome; features never see it (their inputs are knowable before
as_of and exclude the session's own bar, app.features.inputs).

Prices: split/bonus-adjusted bars as known NOW (pit.bars_adjusted with as_of =
now), so a corporate action with ex-date T adjusts close(T-1) and every ratio
below is on one basis. LOW-confidence history is refused there, as in Stage 3.

  ret_cc    close(T) / close(T-1) - 1        T-1 = the previous trading session
  gap       open(T)  / close(T-1) - 1
  ret_oc    close(T) / open(T)    - 1
  high_exc  high(T)  / open(T)    - 1
  low_exc   low(T)   / open(T)    - 1
  hit_up_1, hit_up_2   1 if high(T) >= open(T) * (1 + 1% / 2%) else 0
  hit_dn_1, hit_dn_2   1 if low(T)  <= open(T) * (1 - 1% / 2%) else 0

Limitation: from daily bars the ORDER of an up and a down hit within T is unknown.
No production target is chosen here (Stage 4 target selection is research).
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.canon import pit
from app.core.clock import IST, now
from app.features.engine import batch_rows

VERSION = "label-v1"
LABELS = ("ret_cc", "gap", "ret_oc", "high_exc", "low_exc", "hit_up_1", "hit_up_2",
          "hit_dn_1", "hit_dn_2")
COLUMNS = ("label_version", "session_date", "instrument_key", "label_id", "value", "status",
           "label_start_at", "label_end_at", "inputs_sha256", "computed_at")


def compute(prev: dict | None, bar: dict, prev_session: _dt.date | None) -> dict[str, float | None]:
    o, h, lo, c = (float(bar[k]) for k in ("open", "high", "low", "close"))
    pc = float(prev["close"]) if prev and prev["market_date"] == prev_session else None
    out: dict[str, float | None] = {
        "ret_cc": c / pc - 1 if pc else None, "gap": o / pc - 1 if pc else None,
        "ret_oc": c / o - 1 if o > 0 else None, "high_exc": h / o - 1 if o > 0 else None,
        "low_exc": lo / o - 1 if o > 0 else None}
    for x, n in ((0.01, 1), (0.02, 2)):
        out[f"hit_up_{n}"] = (1.0 if h >= o * (1 + x) else 0.0) if o > 0 else None
        out[f"hit_dn_{n}"] = (1.0 if lo <= o * (1 - x) else 0.0) if o > 0 else None
    return {k: (None if v is None else float(f"{v:.12g}")) for k, v in out.items()}


async def build(s: AsyncSession, start: _dt.date, end: _dt.date,
                keys: list[str] | None = None) -> dict[str, Any]:
    cal = {r[0]: (r[1], r[2]) for r in (await s.execute(text("""select session_date, open_ist,
        close_ist from trading_session where is_trading_day and session_date between :a and :b
        """), {"a": start - _dt.timedelta(days=10), "b": end})).all()}
    days = sorted(cal)
    prev_of = {d: (days[i - 1] if i else None) for i, d in enumerate(days)}
    if keys is None:
        keys = list((await s.execute(text("""select instrument_key from canon_instrument
            where included and segment in ('NSE_EQ', 'NSE_INDEX') order by 1"""))).scalars())
    at, inserted, rows_total, missing, drift = now(), 0, 0, 0, 0
    step = batch_rows(len(COLUMNS))
    for key in keys:
        adj = await pit.bars_adjusted(s, key, "1d", at, start=start - _dt.timedelta(days=10),
                                      end=end)
        bars = adj["rows"]
        values = []
        for i, b in enumerate(bars):
            d = b["market_date"]
            if d < start or d not in cal or None in cal[d]:
                continue              # a session without calendar times has no label window
            prev = bars[i - 1] if i else None
            res = compute(prev, b, prev_of[d])
            sha = hashlib.sha256(json.dumps(
                [[x["market_date"], x["open"], x["high"], x["low"], x["close"],
                  x["payload_sha256"], x["factor_applied"]] for x in (prev, b) if x],
                default=str).encode()).hexdigest()
            o_ist, c_ist = cal[d]
            st_at = _dt.datetime.combine(d, o_ist, tzinfo=IST)
            en_at = _dt.datetime.combine(d, c_ist, tzinfo=IST)
            for lid in LABELS:
                v = res[lid]
                missing += v is None
                values.append({"label_version": VERSION, "session_date": d,
                               "instrument_key": key, "label_id": lid, "value": v,
                               "status": "VALID" if v is not None else "MISSING_INPUT",
                               "label_start_at": st_at, "label_end_at": en_at,
                               "inputs_sha256": sha, "computed_at": at})
        for i in range(0, len(values), step):
            chunk = values[i:i + step]
            binds, params = [], {}
            for j, v in enumerate(chunk):
                binds.append("(" + ", ".join(f":{c}_{j}" for c in COLUMNS) + ")")
                params.update({f"{c}_{j}": v[c] for c in COLUMNS})
            inserted += (await s.execute(text(
                f"insert into training_label ({', '.join(COLUMNS)}) values {', '.join(binds)} "  # noqa: S608
                "on conflict on constraint uq_training_label do nothing"), params)).rowcount
        stored = {(r[0], r[1]): r[2] for r in (await s.execute(text("""select session_date,
            label_id, value from training_label where label_version = :v and instrument_key = :k
              and session_date between :a and :b"""),
            {"v": VERSION, "k": key, "a": start, "b": end})).all()}
        # a stored label is never overwritten; one that a recompute disagrees with is counted
        drift += sum(1 for v in values
                     if stored.get((v["session_date"], v["label_id"]), "absent") != v["value"])
        rows_total += len(values)
        await s.commit()
    untimed = sorted(str(d) for d, t in cal.items() if None in t and d >= start)
    return {"label_version": VERSION, "sessions_without_calendar_times": untimed,
            "instruments": len(keys), "rows": rows_total,
            "inserted": inserted, "missing": missing, "drift_vs_stored": drift}
