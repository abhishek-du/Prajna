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
from decimal import Decimal
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


class FrozenLabelVersion(RuntimeError):
    """label-v1 was built under features-v2 code (2026-10-08); it is never extended."""


async def build(s: AsyncSession, start: _dt.date, end: _dt.date,
                keys: list[str] | None = None, *, frozen_ok: bool = False) -> dict[str, Any]:
    """label-v1 (FROZEN since builder v3: use build_v2). `frozen_ok` exists only for the
    tests that pin the label-v1 definitions on the test database."""
    if not frozen_ok:
        raise FrozenLabelVersion("label-v1 is frozen (features-v2 code); build label-v2")
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


# ── label-v2 (builder v3, 2026-10-09) ─────────────────────────────────────────────
VERSION2 = "label-v2"
EXTREME = 0.25
COLUMNS2 = (*COLUMNS, "flags", "reason", "run_id")
V2_DOC = """label-v2: the label-v1 definitions (the nine labels above, session T open -> T
close), with
  price basis   pit.bars_adjusted as of a RECORDED knowledge cutoff, with the features-v4
                code (corporate actions knowable when observed; per-payload vendor basis)
  explicit rows instead of silence (status MISSING_INPUT, reason):
                BAR_REFUSED          a canonical T bar the adjusted view refuses (LOW /
                                     RECONSTRUCTED basis): every label of (T, instrument)
                MALFORMED_BAR        a T bar with high < low, open/close outside [low, high]
                                     or a non-positive price: every label
                PREV_SESSION_MISSING no usable bar on the previous trading session: ret_cc,
                                     gap (PREV_MALFORMED if that bar is malformed)
  flags (on every label row of (T, instrument)):
                CA_EX_T:<ca_id>:<factor>   an EXACT split/bonus factor with ex-date T,
                                     knowable before the cutoff (applied to T-1)
                UNSUPPORTED_CA_EX_T:<type> another action with ex-date T and no exact
                                     factor (rights, unsupported): prices NOT adjusted for it
                DIVIDEND_EX_T        a dividend goes ex on T (never a price factor)
                EXTREME_UNEXPLAINED  |ret_cc| or |gap| > 25% and no CA_EX_T
                AMBIGUOUS_ORDER_1/_2 the up and the down threshold were both touched on T:
                                     daily OHLC cannot order them; any target/stop use of
                                     these rows is undetermined
No target/stop (first-touch) label is defined (horizon, entry, exit, levels, ties and
costs are undecided)."""


def _malformed(b: dict) -> bool:
    o, h, lo, c = (float(b[k]) for k in ("open", "high", "low", "close"))
    return min(o, h, lo, c) <= 0 or h < lo or not (lo <= o <= h) or not (lo <= c <= h)


def v2_rows(key: str, canon_days: list[_dt.date], adj: dict[_dt.date, dict],
            actions: dict[_dt.date, list[dict]], cal: dict, prev_of: dict) -> list[dict]:
    """Pure: the label-v2 rows of one instrument (without run bookkeeping)."""
    out = []
    for d in canon_days:
        if d not in cal or None in cal[d]:
            continue
        o_ist, c_ist = cal[d]
        st_at = _dt.datetime.combine(d, o_ist, tzinfo=IST)
        en_at = _dt.datetime.combine(d, c_ist, tzinfo=IST)
        flags = []
        exact = False
        for a in actions.get(d, []):
            if a["status"] == "EXACT" and a["action_type"] in ("SPLIT", "BONUS"):
                flags.append(f"CA_EX_T:{a['id']}:{Decimal(a['factor']).normalize()}")
                exact = True
            elif a["action_type"] == "DIVIDEND":
                flags.append("DIVIDEND_EX_T")
            else:
                flags.append(f"UNSUPPORTED_CA_EX_T:{a['action_type']}")
        bar = adj.get(d)
        vals: dict[str, float | None] = dict.fromkeys(LABELS)
        reasons: dict[str, str | None] = dict.fromkeys(LABELS)
        if bar is None:
            reasons = dict.fromkeys(LABELS, "BAR_REFUSED")
            src = []
        elif _malformed(bar):
            reasons = dict.fromkeys(LABELS, "MALFORMED_BAR")
            src = [bar]
        else:
            pd = prev_of.get(d)
            prev = adj.get(pd) if pd else None
            if prev is not None and _malformed(prev):
                pprev, why = None, "PREV_MALFORMED"
            else:
                pprev, why = prev, "PREV_SESSION_MISSING"
            vals = compute(pprev, bar, pd)
            for k in ("ret_cc", "gap"):
                if vals[k] is None:
                    reasons[k] = why
            src = [x for x in (pprev, bar) if x]
            if not exact and any(vals[k] is not None and abs(vals[k]) > EXTREME
                                 for k in ("ret_cc", "gap")):
                flags.append("EXTREME_UNEXPLAINED")
            for n in (1, 2):
                if vals[f"hit_up_{n}"] == 1.0 and vals[f"hit_dn_{n}"] == 1.0:
                    flags.append(f"AMBIGUOUS_ORDER_{n}")
        sha = hashlib.sha256(json.dumps(
            [[x["market_date"], x["open"], x["high"], x["low"], x["close"], x["payload_sha256"],
              x["factor_applied"]] for x in src], default=str).encode()).hexdigest()
        flags = sorted(flags)
        for lid in LABELS:
            v = vals[lid]
            out.append({"label_version": VERSION2, "session_date": d, "instrument_key": key,
                        "label_id": lid, "value": v,
                        "status": "VALID" if v is not None else "MISSING_INPUT",
                        "label_start_at": st_at, "label_end_at": en_at, "inputs_sha256": sha,
                        "flags": flags, "reason": None if v is not None else reasons[lid]})
    return out


def _digest(rows: list[dict]) -> str:
    body = sorted((str(r["session_date"]), r["instrument_key"], r["label_id"], r["value"],
                   r["status"], r["reason"], r["inputs_sha256"], r["flags"]) for r in rows)
    return hashlib.sha256(json.dumps(body, default=str).encode()).hexdigest()


async def source_fingerprints(s: AsyncSession, start: _dt.date, end: _dt.date,
                              cutoff: _dt.datetime) -> dict[str, Any]:
    out = {}
    for name, sql in (
        ("bars_1d", """select count(*), md5(string_agg(md5(concat_ws('|', instrument_key,
              market_date, open, high, low, close, volume, payload_sha256)), '' order by
              instrument_key, market_date)) from canon_market_bar where timeframe = '1d'
              and market_date between :a and :b and knowable_at < :c"""),
        ("corporate_actions", """select count(*), md5(string_agg(md5(concat_ws('|', id,
              action_type, ex_date, knowable_at)), '' order by id)) from canon_corporate_action
              where knowable_at < :c"""),
        ("ca_factors", """select count(*), md5(string_agg(md5(concat_ws('|', ca_id, status,
              factor_price, vendor_applied, knowable_at)), '' order by ca_id))
              from canon_ca_factor where knowable_at < :c"""),
        ("ca_adjustment_observations", """select count(*), md5(string_agg(md5(concat_ws('|',
              instrument_key, bar_start_utc, fetched_at)), '' order by instrument_key,
              bar_start_utc, fetched_at)) from ohlcv_observation
              where classification = 'CA_ADJUSTMENT' and fetched_at < :c""")):
        n, h = (await s.execute(text(sql), {"a": start - _dt.timedelta(days=10), "b": end,
                                             "c": cutoff})).one()
        out[name] = {"rows": n, "md5": h}
    return out


async def build_v2(s: AsyncSession, start: _dt.date, end: _dt.date, *,
                   cutoff: _dt.datetime, keys: list[str] | None = None,
                   code_git_sha: str = "unknown") -> dict[str, Any]:
    """label-v2 for sessions in [start, end], read at `cutoff`, in ONE transaction
    (the run row and every label row commit together; the FK is deferred)."""
    import uuid

    from app.features import registry as R
    from app.features.engine import consistent_read
    started = now()
    await s.rollback()
    await consistent_read(s, read_only=False)
    cal = {r[0]: (r[1], r[2]) for r in (await s.execute(text("""select session_date, open_ist,
        close_ist from trading_session where is_trading_day and session_date between :a and :b
        """), {"a": start - _dt.timedelta(days=10), "b": end})).all()}
    days = sorted(cal)
    prev_of = {d: (days[i - 1] if i else None) for i, d in enumerate(days)}
    if keys is None:
        keys = list((await s.execute(text("""select instrument_key from canon_instrument
            where included and segment in ('NSE_EQ', 'NSE_INDEX') order by 1"""))).scalars())
    fps = await source_fingerprints(s, start, end, cutoff)
    acts: dict[str, dict[_dt.date, list[dict]]] = {}
    for r in (await s.execute(text("""select a.id, a.instrument_key, a.action_type, a.ex_date,
            f.status, f.factor_price from canon_corporate_action a
            left join canon_ca_factor f on f.ca_id = a.id and f.knowable_at < :c
            where a.knowable_at < :c and a.ex_date between :a and :b"""),
            {"c": cutoff, "a": start, "b": end})).mappings().all():
        acts.setdefault(r["instrument_key"], {}).setdefault(r["ex_date"], []).append(
            {"id": r["id"], "action_type": r["action_type"], "status": r["status"],
             "factor": r["factor_price"]})
    run_id = uuid.uuid4()
    digests, rows_total, inserted, drift, counts = [], 0, 0, 0, {}
    step = batch_rows(len(COLUMNS2))
    for key in keys:
        canon = list((await s.execute(text("""select market_date from canon_market_bar
            where instrument_key = :k and timeframe = '1d' and market_date between :a and :b
              and knowable_at < :c order by 1"""),
            {"k": key, "a": start, "b": end, "c": cutoff})).scalars())
        if not canon:
            continue
        adj = {r["market_date"]: r for r in (await pit.bars_adjusted(
            s, key, "1d", cutoff, start=start - _dt.timedelta(days=10), end=end))["rows"]}
        rows = v2_rows(key, canon, adj, acts.get(key, {}), cal, prev_of)
        digests.append(_digest(rows))
        for r in rows:
            r.update(computed_at=started, run_id=run_id)
            k = r["reason"] or ("FLAGGED" if r["flags"] else "VALID")
            counts[k] = counts.get(k, 0) + 1
        for i in range(0, len(rows), step):
            chunk = rows[i:i + step]
            binds, params = [], {}
            for j, v in enumerate(chunk):
                binds.append("(" + ", ".join(f":{c}_{j}" for c in COLUMNS2) + ")")
                params.update({f"{c}_{j}": v[c] for c in COLUMNS2})
            inserted += (await s.execute(text(
                f"insert into training_label ({', '.join(COLUMNS2)}) values {', '.join(binds)} "  # noqa: S608
                "on conflict on constraint uq_training_label do nothing"), params)).rowcount
        stored = {(r[0], r[1]): (r[2], r[3], r[4]) for r in (await s.execute(text("""
            select session_date, label_id, value, reason, flags from training_label
            where label_version = :v and instrument_key = :k and session_date between :a and :b
            """), {"v": VERSION2, "k": key, "a": start, "b": end})).all()}
        drift += sum(1 for r in rows if stored.get((r["session_date"], r["label_id"]))
                     != (r["value"], r["reason"], r["flags"]))
        rows_total += len(rows)
    rows_sha = hashlib.sha256("".join(digests).encode()).hexdigest()
    summary = {"rows": rows_total, "inserted": inserted, "drift_vs_stored": drift,
               "by_reason_or_flag": dict(sorted(counts.items())), "definition": V2_DOC,
               "extreme_threshold": EXTREME}
    await s.execute(text("""insert into training_label_run (run_id, label_version,
        knowledge_cutoff, registry_sha256, code_git_sha, start_date, end_date, instruments,
        rows, rows_sha256, source_fingerprints, summary, started_at, completed_at)
        values (:r, :v, :c, :rh, :g, :a, :b, :n, :rows, :h, cast(:fp as jsonb),
                cast(:sm as jsonb), :st, :en)"""),
        {"r": run_id, "v": VERSION2, "c": cutoff, "rh": R.REGISTRY_SHA256, "g": code_git_sha,
         "a": start, "b": end, "n": len(digests), "rows": rows_total, "h": rows_sha,
         "fp": json.dumps(fps), "sm": json.dumps(summary, default=str), "st": started,
         "en": now()})
    await s.commit()
    return {"run_id": str(run_id), "label_version": VERSION2, "cutoff": cutoff.isoformat(),
            "rows_sha256": rows_sha, "instruments": len(digests), "source_fingerprints": fps,
            **{k: v for k, v in summary.items() if k != "definition"}}
