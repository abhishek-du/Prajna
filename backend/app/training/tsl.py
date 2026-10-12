"""label-tsl-long-v1: one-session long target/stop outcome (contract approved by the user
2026-10-12: k = 1.5, gross returns only).

Timing     entry_session T = the snapshot's session_date; information = sessions < T;
           signal instant = PRE_SESSION as_of (T 08:59:59 IST). PRE_OPEN is not used.
           Window: T open -> T close (label_start_at > as_of).
Entry      E = session T's official open (the vendor daily bar's open): a MODELLED entry
           proxy, not a guaranteed fill.
R          R = E x atr_pct_14(T, PRE_SESSION) x k, k = 1.5; atr_pct_14 is the dataset's
           own feature row (knowable before as_of), so each dataset has its own label
           version: label-tsl-long-v1-strict / label-tsl-long-v1-asif.
Barriers   from E, rounded conservatively to the tick (tick = instrument.tick_size / 100):
           target = ceil_tick(E + 2R), stop = ceil_tick(E - R); stop > E - tick ->
           INVALID R_BELOW_TICK.
Touch      target hit: high >= target; stop hit: low <= stop.
Outcome    only target -> TARGET_HIT (+1), exit at target; only stop -> STOP_HIT (-1), exit
           at stop; neither -> HORIZON_EXIT (0), exit at the official close.
           Both -> resolved only with valid 1-minute bars (their max high and min low equal
           the daily high and low, and the first target touch and the first stop touch fall
           in different minutes); otherwise AMBIGUOUS (MISSING_INPUT, AMBIGUOUS_ORDER).
Values     tsl_l_k1p5_outcome (+1 / -1 / 0), tsl_l_k1p5_gross_ret = exit / E - 1,
           tsl_l_k1p5_r_multiple = (exit - E) / (E - stop). Gross only: no cost model
           (net returns NOT IMPLEMENTED).
Exclusions MISSING_INPUT, value null (never 0), reason ATR_NOT_VALID / BAR_REFUSED /
           MALFORMED_BAR / SPECIAL_SESSION / R_BELOW_TICK / AMBIGUOUS_ORDER / NO_TICK_SIZE.
Flags      RESOLUTION_DAILY / RESOLUTION_1M / RESOLUTION_1M_SAME_MINUTE /
           RESOLUTION_1M_INCONSISTENT / RESOLUTION_NO_1M; CA_EX_T:<id>:<f>,
           UNSUPPORTED_CA_EX_T:<type>, DIVIDEND_EX_T (as label-v2);
           PRICE_LEVEL_VENDOR_ADJUSTED:<F> when the stored bar carries a vendor-applied
           factor F (prices are brought back to the traded level, x F, before rounding).
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import uuid
from decimal import ROUND_CEILING, Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.canon import pit
from app.core.clock import IST, now
from app.features.engine import batch_rows
from app.training import labels as L

BASE = "label-tsl-long-v1"
K = Decimal("1.5")
OUTCOME, GROSS, RMULT = "tsl_l_k1p5_outcome", "tsl_l_k1p5_gross_ret", "tsl_l_k1p5_r_multiple"
IDS = (OUTCOME, GROSS, RMULT)
TARGET_R, STOP_R = Decimal(2), Decimal(1)


def version(dataset_name: str) -> str:
    if dataset_name not in ("strict", "asif"):
        raise ValueError(f"unknown dataset {dataset_name!r}")
    return f"{BASE}-{dataset_name}"


def ceil_tick(x: Decimal, tick: Decimal) -> Decimal:
    return (x / tick).to_integral_value(ROUND_CEILING) * tick


def outcome(e: Decimal, h: Decimal, lo: Decimal, c: Decimal, tick: Decimal,
            atr_pct: float | None, minutes: list[tuple[Any, Decimal, Decimal]] | None,
            k: Decimal = K) -> dict[str, Any]:
    """Pure. -> {"outcome", "gross", "r", "reason", "flags", "target", "stop"}."""
    res: dict[str, Any] = {"outcome": None, "gross": None, "r": None, "reason": None,
                           "flags": [], "target": None, "stop": None}
    if atr_pct is None:
        res["reason"] = "ATR_NOT_VALID"
        return res
    r_raw = e * Decimal(str(atr_pct)) * k
    target = ceil_tick(e + TARGET_R * r_raw, tick)
    stop = ceil_tick(e - STOP_R * r_raw, tick)
    res.update(target=target, stop=stop)
    if stop > e - tick:
        res["reason"] = "R_BELOW_TICK"
        return res
    hit_t, hit_s = h >= target, lo <= stop
    if hit_t and hit_s:
        if not minutes:
            res["flags"].append("RESOLUTION_NO_1M")
            res["reason"] = "AMBIGUOUS_ORDER"
            return res
        mh, ml = max(m[1] for m in minutes), min(m[2] for m in minutes)
        if mh != h or ml != lo:
            res["flags"].append("RESOLUTION_1M_INCONSISTENT")
            res["reason"] = "AMBIGUOUS_ORDER"
            return res
        ft = min(m[0] for m in minutes if m[1] >= target)
        fs = min(m[0] for m in minutes if m[2] <= stop)
        if ft == fs:
            res["flags"].append("RESOLUTION_1M_SAME_MINUTE")
            res["reason"] = "AMBIGUOUS_ORDER"
            return res
        res["flags"].append("RESOLUTION_1M")
        code, exit_ = (1, target) if ft < fs else (-1, stop)
    elif hit_t:
        res["flags"].append("RESOLUTION_DAILY")
        code, exit_ = 1, target
    elif hit_s:
        res["flags"].append("RESOLUTION_DAILY")
        code, exit_ = -1, stop
    else:
        res["flags"].append("RESOLUTION_DAILY")
        code, exit_ = 0, c
    res["outcome"] = float(code)
    res["gross"] = float(f"{float(exit_ / e - 1):.12g}")
    res["r"] = float(f"{float((exit_ - e) / (e - stop)):.12g}")
    return res


def _malformed(o: Decimal, h: Decimal, lo: Decimal, c: Decimal) -> bool:
    return min(o, h, lo, c) <= 0 or h < lo or not (lo <= o <= h) or not (lo <= c <= h)


async def _baked(s: AsyncSession, key: str) -> dict[str, list[tuple]]:
    """payload -> [(ex_date, factor, ca_id)] the vendor applied to that payload (the
    pit.bars_adjusted rule, F3-PAYLOAD-BASIS included)."""
    events = (await s.execute(text("""select ca_id, ex_date, factor_price from canon_ca_factor
        where instrument_key = :k and status = 'EXACT' and vendor_applied = 'APPLIED'
          and ex_date is not null"""), {"k": key})).all()
    if not events:
        return {}
    raw_for = {(r[0], int(r[1])) for r in (await s.execute(text("""
        select distinct b.payload_sha256, jsonb_array_elements_text(o.explained_by -> 'ca_ids')
        from ohlcv_observation o join ohlcv_bar b on b.instrument_id = o.instrument_id
         and b.timeframe = o.timeframe and b.bar_start_utc = o.bar_start_utc
         and o.fetched_at > b.fetched_at
        where o.instrument_key = :k and o.timeframe = '1d'
          and o.classification = 'CA_ADJUSTMENT'"""), {"k": key})).all()}
    return {"events": events, "raw_for": raw_for}  # type: ignore[dict-item]


def _factor(bd: _dt.date, payload: str, basis: tuple | None, baked: dict) -> Decimal:
    if not baked or not basis or basis[0] != "VENDOR_ADJUSTED":
        return Decimal(1)
    f = Decimal(1)
    for ca, ex, fp in baked["events"]:
        if bd < ex <= basis[1] and (payload, ca) not in baked["raw_for"]:
            f *= Decimal(fp)
    return f


async def build(s: AsyncSession, dataset_name: str, start: _dt.date, end: _dt.date, *,
                cutoff: _dt.datetime, code_git_sha: str = "unknown",
                keys: list[str] | None = None) -> dict[str, Any]:
    """label-tsl-long-v1-<dataset> for the dataset's PRE_SESSION snapshots in [start, end],
    read at `cutoff`, in ONE transaction (run row + label rows; deferred FK)."""
    from app.features import registry as R
    from app.features.engine import consistent_read
    from app.training import policy as P
    ds = P.DATASETS[dataset_name]
    lv = version(dataset_name)
    started = now()
    await s.rollback()
    await consistent_read(s, read_only=False)
    cal = {r[0]: (r[1], r[2], r[3]) for r in (await s.execute(text("""select session_date,
        open_ist, close_ist, session_type from trading_session where is_trading_day
          and session_date between :a and :b"""), {"a": start, "b": end})).all()}
    atr: dict[str, dict[_dt.date, tuple]] = {}
    for k, d, v, st, kn, a in (await s.execute(text("""select instrument_key, session_date,
            value, status, input_max_knowable_at, as_of from training_feature_value
            where dataset_version = :v and snapshot = 'PRE_SESSION' and feature_id = 'atr_pct_14'
              and instrument_key like 'NSE_EQ|%%' and session_date between :a and :b"""),
            {"v": ds.version, "a": start, "b": end})).all():
        if keys is None or k in keys:
            atr.setdefault(k, {})[d] = (v if st == "VALID" else None, kn, a)
    acts: dict[str, dict[_dt.date, list[dict]]] = {}
    for r in (await s.execute(text("""select a.id, a.instrument_key, a.action_type, a.ex_date,
            f.status, f.factor_price from canon_corporate_action a
            left join canon_ca_factor f on f.ca_id = a.id and f.knowable_at < :c
            where a.knowable_at < :c and a.ex_date between :a and :b"""),
            {"c": cutoff, "a": start, "b": end})).mappings().all():
        acts.setdefault(r["instrument_key"], {}).setdefault(r["ex_date"], []).append(
            {"id": r["id"], "action_type": r["action_type"], "status": r["status"],
             "factor": r["factor_price"]})
    ticks = {r[0]: r[1] for r in (await s.execute(text("""select instrument_key, tick_size
        from instrument where valid_to = 'infinity' and segment = 'NSE_EQ'"""))).all()}
    fps = await L.source_fingerprints(s, start, end, cutoff)
    fps["atr_pct_14"] = dict(zip(("rows", "md5"), (await s.execute(text("""select count(*),
        md5(string_agg(md5(concat_ws('|', instrument_key, session_date, value, status,
          inputs_sha256)), '' order by instrument_key, session_date))
        from training_feature_value where dataset_version = :v and snapshot = 'PRE_SESSION'
          and feature_id = 'atr_pct_14' and session_date between :a and :b"""),
        {"v": ds.version, "a": start, "b": end})).one(), strict=True))
    fps["bars_1m"] = dict(zip(("rows", "md5"), (await s.execute(text("""select count(*),
        md5(string_agg(md5(concat_ws('|', instrument_key, bar_start_utc, high, low)), ''
          order by instrument_key, bar_start_utc)) from canon_market_bar where timeframe = '1m'
          and market_date between :a and :b and knowable_at < :c"""),
        {"a": start, "b": end, "c": cutoff})).one(), strict=True))
    run_id = uuid.uuid4()
    cols = L.COLUMNS2
    step = batch_rows(len(cols))
    digests, total, inserted, drift, counts = [], 0, 0, 0, {}
    for key in sorted(atr):
        sess = atr[key]
        stored = {r[0]: r for r in (await s.execute(text("""select b.market_date, b.open, b.high,
            b.low, b.close, b.payload_sha256, pb.price_basis, pb.basis_as_of
            from canon_market_bar b left join ohlcv_payload_basis pb using (payload_sha256)
            where b.instrument_key = :k and b.timeframe = '1d' and b.market_date between :a
              and :b and b.knowable_at < :c"""),
            {"k": key, "a": start, "b": end, "c": cutoff})).all()}
        adj = {r["market_date"] for r in (await pit.bars_adjusted(
            s, key, "1d", cutoff, start=start, end=end))["rows"]}
        baked = await _baked(s, key)
        mins: dict[_dt.date, list[tuple]] = {}
        for d, ts, hh, ll in (await s.execute(text("""select market_date, bar_start_utc, high,
                low from canon_market_bar where instrument_key = :k and timeframe = '1m'
                  and market_date between :a and :b and knowable_at < :c"""),
                {"k": key, "a": start, "b": end, "c": cutoff})).all():
            mins.setdefault(d, []).append((ts, Decimal(str(hh)), Decimal(str(ll))))
        tk = ticks.get(key)
        rows = []
        for d in sorted(sess):
            a_val, a_kn, as_of = sess[d]
            o_ist, c_ist, stype = cal.get(d, (None, None, None))
            flags, reason, res = [], None, None
            for a in acts.get(key, {}).get(d, []):
                if a["status"] == "EXACT" and a["action_type"] in ("SPLIT", "BONUS"):
                    flags.append(f"CA_EX_T:{a['id']}:{Decimal(a['factor']).normalize()}")
                elif a["action_type"] == "DIVIDEND":
                    flags.append("DIVIDEND_EX_T")
                else:
                    flags.append(f"UNSUPPORTED_CA_EX_T:{a['action_type']}")
            b = stored.get(d)
            if stype != "NORMAL" or o_ist is None or c_ist is None:
                reason = "SPECIAL_SESSION"
            elif b is None or d not in adj:
                reason = "BAR_REFUSED"
            elif tk is None:
                reason = "NO_TICK_SIZE"
            else:
                f = _factor(d, b[5], (b[6], b[7]) if b[6] else None, baked)
                o, hh, ll, cc = (Decimal(str(x)) * f for x in b[1:5])
                if f != 1:
                    flags.append(f"PRICE_LEVEL_VENDOR_ADJUSTED:{f.normalize()}")
                if _malformed(o, hh, ll, cc):
                    reason = "MALFORMED_BAR"
                else:
                    res = outcome(o, hh, ll, cc, Decimal(str(tk)) / 100, a_val, mins.get(d))
                    reason = res["reason"]
                    flags += res["flags"]
            start_at = (_dt.datetime.combine(d, o_ist, tzinfo=IST) if o_ist
                        else _dt.datetime.combine(d, _dt.time(9, 15), tzinfo=IST))
            end_at = (_dt.datetime.combine(d, c_ist, tzinfo=IST) if c_ist
                      else start_at + _dt.timedelta(hours=6, minutes=15))
            if start_at <= as_of:
                raise AssertionError(f"{key} {d}: label start {start_at} <= as_of {as_of}")
            sha = hashlib.sha256(json.dumps([str(x) for x in (b or ())] + [a_val, str(a_kn)],
                                            default=str).encode()).hexdigest()
            vals = {OUTCOME: res["outcome"] if res else None,
                    GROSS: res["gross"] if res else None, RMULT: res["r"] if res else None}
            fl = sorted(flags)
            for lid in IDS:
                v = vals[lid] if reason is None else None
                rows.append({"label_version": lv, "session_date": d, "instrument_key": key,
                             "label_id": lid, "value": v,
                             "status": "VALID" if v is not None else "MISSING_INPUT",
                             "label_start_at": start_at, "label_end_at": end_at,
                             "inputs_sha256": sha, "flags": fl,
                             "reason": None if v is not None else reason,
                             "computed_at": started, "run_id": run_id})
            ck = reason or {1.0: "TARGET_HIT", -1.0: "STOP_HIT", 0.0: "HORIZON_EXIT"}[
                res["outcome"]]
            counts[ck] = counts.get(ck, 0) + 1
        digests.append(L._digest(rows))
        for i in range(0, len(rows), step):
            chunk = rows[i:i + step]
            binds, params = [], {}
            for j, v in enumerate(chunk):
                binds.append("(" + ", ".join(f":{c}_{j}" for c in cols) + ")")
                params.update({f"{c}_{j}": v[c] for c in cols})
            inserted += (await s.execute(text(
                f"insert into training_label ({', '.join(cols)}) values {', '.join(binds)} "  # noqa: S608
                "on conflict on constraint uq_training_label do nothing"), params)).rowcount
        have = {(r[0], r[1]): (r[2], r[3], r[4]) for r in (await s.execute(text("""
            select session_date, label_id, value, reason, flags from training_label
            where label_version = :v and instrument_key = :k and session_date between :a and :b
            """), {"v": lv, "k": key, "a": start, "b": end})).all()}
        drift += sum(1 for r in rows if have.get((r["session_date"], r["label_id"]))
                     != (r["value"], r["reason"], r["flags"]))
        total += len(rows)
    rows_sha = hashlib.sha256("".join(digests).encode()).hexdigest()
    summary = {"rows": total, "inserted": inserted, "drift_vs_stored": drift,
               "outcomes": dict(sorted(counts.items())), "k": str(K), "dataset": ds.version,
               "costs": "NOT_APPLIED (gross only; net NOT IMPLEMENTED)",
               "rounding": "target = ceil_tick(E + 2R), stop = ceil_tick(E - R); "
                           "stop > E - tick -> R_BELOW_TICK",
               "resolution": "1m only when 1m max high = daily high, 1m min low = daily low "
                             "and the first touches fall in different minutes",
               "definition": __doc__}
    await s.execute(text("""insert into training_label_run (run_id, label_version,
        knowledge_cutoff, registry_sha256, code_git_sha, start_date, end_date, instruments,
        rows, rows_sha256, source_fingerprints, summary, started_at, completed_at)
        values (:r, :v, :c, :rh, :g, :a, :b, :n, :rows, :h, cast(:fp as jsonb),
                cast(:sm as jsonb), :st, :en)"""),
        {"r": run_id, "v": lv, "c": cutoff, "rh": R.REGISTRY_SHA256, "g": code_git_sha,
         "a": start, "b": end, "n": len(digests), "rows": total, "h": rows_sha,
         "fp": json.dumps(fps, default=str), "sm": json.dumps(summary, default=str),
         "st": started, "en": now()})
    await s.commit()
    return {"run_id": str(run_id), "label_version": lv, "cutoff": cutoff.isoformat(),
            "rows_sha256": rows_sha, "instruments": len(digests), "source_fingerprints": fps,
            **{k: v for k, v in summary.items() if k != "definition"}}
