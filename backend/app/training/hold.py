"""label-hold5-v1-asif: the E2 multi-session holding labels (Amendment 2 rev 2,
PROPOSED; building it in production needs its own approval - NOT RUN).

One price basis for the whole window: pit.bars_adjusted (split/bonus EXACT factors) as
of ONE recorded knowledge cutoff, so the book's open-to-open path is consistent. Holding
periods count TRADING SESSIONS of the calendar (trading_session), never instrument
bars: a session without a usable bar is a gap, not skipped.

  open_adj    the adjusted official open of T (the E2 book's price; window T open ->
              T close)
  hold5_px    open[T+5] / open[T] - 1   (e2.hold_label; window T open -> T+5 open)
  hold3_px    open[T+3] / open[T] - 1   (the H = 3 sensitivity)
  hold5_tr    hold5_px plus the cash of every DIVIDEND with ex-date in (T, T+5],
  hold3_tr    per share on the adjusted basis (divided by the EXACT split/bonus factors
              with a later ex-date inside the window). Total return at LABEL level
              only: the E2 book has no dividend cash accounting.
Rows are explicit (status MISSING_INPUT, value null, never 0), reason:
  BAR_REFUSED        no adjusted bar for T (absent, LOW or RECONSTRUCTED basis)
  MALFORMED_BAR      T's bar has high < low, open/close outside [low, high], or a
                     non-positive price
  SESSION_MISSING    no usable open at T + h
  NO_EXIT_SESSION    T + h is beyond the window's last calendar session
  NO_CALENDAR_TIMES  the session has no open/close times
Flags (hold rows): CA_IN_WINDOW:<id> (an EXACT split/bonus with ex in (T, T+h]),
UNSUPPORTED_CA_IN_WINDOW:<type>, DIVIDEND_IN_WINDOW, DIVIDEND_NO_AMOUNT (a dividend in
the window without an amount: the _tr row is MISSING_INPUT). Flags never select.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.canon import pit
from app.core.clock import IST, now
from app.features.engine import batch_rows
from app.training import e2 as X
from app.training import labels as L

VERSION = "label-hold5-v1-asif"
HORIZONS = (5, 3)
IDS = ("open_adj", "hold5_px", "hold5_tr", "hold3_px", "hold3_tr")
COLUMNS = L.COLUMNS2


def hold_rows(key: str, days: list[_dt.date], canon: set[_dt.date], adj: dict[_dt.date, dict],
              actions: dict[_dt.date, list[dict]], cal: dict) -> list[dict]:
    """Pure: the rows of one instrument. days: the calendar sessions of the window plus
    up to max(HORIZONS) exit sessions after it; a row is emitted for every T in days
    with a canonical bar (canon), exactly as label-v2. actions: EVERY action of the
    instrument knowable at the cutoff (a split after the window, before the cutoff,
    also rescales the window's prices, so it rescales a dividend's cash too)."""
    split_after = sorted((x, float(a["factor"])) for x, acts in actions.items() for a in acts
                         if a["action_type"] in ("SPLIT", "BONUS") and a["status"] == "EXACT")
    opens: list[float | None] = []
    why_open: list[str | None] = []
    for d in days:
        b = adj.get(d)
        if b is None:
            opens.append(None)
            why_open.append("BAR_REFUSED")
        elif L._malformed(b):
            opens.append(None)
            why_open.append("MALFORMED_BAR")
        else:
            opens.append(float(b["open"]))
            why_open.append(None)
    out = []
    for t in range(len(days)):
        d = days[t]
        if d not in canon:
            continue
        if d not in cal or None in cal[d]:
            continue
        st_at = _dt.datetime.combine(d, cal[d][0], tzinfo=IST)
        src = [adj[d]] if d in adj else []
        rows = {"open_adj": (opens[t], why_open[t], [],
                             _dt.datetime.combine(d, cal[d][1], tzinfo=IST), src)}
        for h in HORIZONS:
            e = t + h
            end = (_dt.datetime.combine(days[e], cal[days[e]][0], tzinfo=IST)
                   if e < len(days) and days[e] in cal and None not in cal[days[e]]
                   else st_at + _dt.timedelta(days=h))
            flags, divs, no_amount = [], {}, False
            factors = [(x, a) for x in days[t + 1:e + 1] for a in actions.get(x, [])]
            for x, a in factors:
                if a["action_type"] in ("SPLIT", "BONUS") and a["status"] == "EXACT":
                    flags.append(f"CA_IN_WINDOW:{a['id']}")
                elif a["action_type"] == "DIVIDEND":
                    flags.append("DIVIDEND_IN_WINDOW")
                    if a.get("amount") is None:
                        no_amount = True
                        flags.append("DIVIDEND_NO_AMOUNT")
                    else:
                        later = 1.0
                        for y, f in split_after:
                            if y > x:
                                later *= f
                        i = days.index(x)
                        divs[i] = divs.get(i, 0.0) + float(a["amount"]) / later
                else:
                    flags.append(f"UNSUPPORTED_CA_IN_WINDOW:{a['action_type']}")
            flags = sorted(set(flags))
            hsrc = src + ([adj[days[e]]] if e < len(days) and days[e] in adj else [])
            if opens[t] is None:
                px = tr = (None, why_open[t])
            else:
                px = X.hold_label(opens, t, h)
                tr = X.hold_label(opens, t, h, dividends=divs)
                if px[1] is None and no_amount:
                    tr = (None, "DIVIDEND_NO_AMOUNT")
            rows[f"hold{h}_px"] = (*px, flags, end, hsrc)
            rows[f"hold{h}_tr"] = (*tr, flags, end, hsrc)
        for lid in IDS:
            v, why, flags, end, s = rows[lid]
            sha = hashlib.sha256(json.dumps(
                [[x["market_date"], x["open"], x["payload_sha256"], x["factor_applied"]]
                 for x in s], default=str).encode()).hexdigest()
            v = None if v is None else float(f"{v:.12g}")
            out.append({"label_version": VERSION, "session_date": d, "instrument_key": key,
                        "label_id": lid, "value": v,
                        "status": "VALID" if v is not None else "MISSING_INPUT",
                        "label_start_at": st_at, "label_end_at": end, "inputs_sha256": sha,
                        "flags": flags, "reason": None if v is not None else why})
    return out


async def build(s: AsyncSession, start: _dt.date, end: _dt.date, *,
                cutoff: _dt.datetime, keys: list[str] | None = None,
                code_git_sha: str = "unknown") -> dict[str, Any]:
    """label-hold5-v1-asif for sessions in [start, end], read at `cutoff`, in ONE
    transaction (append-only; a rerun inserts 0 and must reproduce rows_sha256).
    Needs the separate production approval: never called by the scheduled pipeline."""
    from app.features import registry as R
    from app.features.engine import consistent_read
    started = now()
    await s.rollback()
    await consistent_read(s, read_only=False)
    horizon = max(HORIZONS)
    cal = {r[0]: (r[1], r[2]) for r in (await s.execute(text("""select session_date, open_ist,
        close_ist from trading_session where is_trading_day and session_date >= :a
        order by 1"""), {"a": start})).all()}
    later = [d for d in sorted(cal) if d > end][:horizon]
    days = [d for d in sorted(cal) if start <= d <= end] + later
    if keys is None:
        keys = list((await s.execute(text("""select instrument_key from canon_instrument
            where included and segment = 'NSE_EQ' order by 1"""))).scalars())
    fps = await L.source_fingerprints(s, start, days[-1], cutoff)
    acts: dict[str, dict[_dt.date, list[dict]]] = {}
    for r in (await s.execute(text("""select a.id, a.instrument_key, a.action_type, a.ex_date,
            a.amount, f.status, f.factor_price from canon_corporate_action a
            left join canon_ca_factor f on f.ca_id = a.id and f.knowable_at < :c
            where a.knowable_at < :c and a.ex_date >= :a and a.ex_date <= :cd"""),
            {"c": cutoff, "a": start, "cd": cutoff.astimezone(IST).date()})).mappings().all():
        # ex_date <= the cutoff's date: exactly the factors pit.bars_adjusted applies
        acts.setdefault(r["instrument_key"], {}).setdefault(r["ex_date"], []).append(
            {"id": r["id"], "action_type": r["action_type"], "status": r["status"],
             "factor": r["factor_price"], "amount": r["amount"]})
    run_id = uuid.uuid4()
    digests, rows_total, inserted, drift, counts = [], 0, 0, 0, {}
    step = batch_rows(len(COLUMNS))
    for key in keys:
        adj = {r["market_date"]: r for r in (await pit.bars_adjusted(
            s, key, "1d", cutoff, start=start, end=days[-1]))["rows"]}
        if not adj:
            continue
        canon = set((await s.execute(text("""select market_date from canon_market_bar
            where instrument_key = :k and timeframe = '1d' and market_date between :a and :b
              and knowable_at < :c"""), {"k": key, "a": start, "b": end, "c": cutoff})).scalars())
        rows = hold_rows(key, days, canon, adj, acts.get(key, {}), cal)
        digests.append(L._digest(rows))
        for r in rows:
            r.update(computed_at=started, run_id=run_id)
            k = r["reason"] or ("FLAGGED" if r["flags"] else "VALID")
            counts[k] = counts.get(k, 0) + 1
        for i in range(0, len(rows), step):
            chunk = rows[i:i + step]
            binds, params = [], {}
            for j, v in enumerate(chunk):
                binds.append("(" + ", ".join(f":{c}_{j}" for c in COLUMNS) + ")")
                params.update({f"{c}_{j}": v[c] for c in COLUMNS})
            inserted += (await s.execute(text(
                f"insert into training_label ({', '.join(COLUMNS)}) values {', '.join(binds)} "  # noqa: S608
                "on conflict on constraint uq_training_label do nothing"), params)).rowcount
        stored = {(r[0], r[1]): (r[2], r[3], r[4]) for r in (await s.execute(text("""
            select session_date, label_id, value, reason, flags from training_label
            where label_version = :v and instrument_key = :k and session_date between :a and :b
            """), {"v": VERSION, "k": key, "a": start, "b": end})).all()}
        drift += sum(1 for r in rows if stored.get((r["session_date"], r["label_id"]))
                     != (r["value"], r["reason"], r["flags"]))
        rows_total += len(rows)
    rows_sha = hashlib.sha256("".join(digests).encode()).hexdigest()
    summary = {"rows": rows_total, "inserted": inserted, "drift_vs_stored": drift,
               "by_reason_or_flag": dict(sorted(counts.items())), "definition": __doc__,
               "exit_sessions_after_end": [str(d) for d in later]}
    await s.execute(text("""insert into training_label_run (run_id, label_version,
        knowledge_cutoff, registry_sha256, code_git_sha, start_date, end_date, instruments,
        rows, rows_sha256, source_fingerprints, summary, started_at, completed_at)
        values (:r, :v, :c, :rh, :g, :a, :b, :n, :rows, :h, cast(:fp as jsonb),
                cast(:sm as jsonb), :st, :en)"""),
        {"r": run_id, "v": VERSION, "c": cutoff, "rh": R.REGISTRY_SHA256, "g": code_git_sha,
         "a": start, "b": end, "n": len(digests), "rows": rows_total, "h": rows_sha,
         "fp": json.dumps(fps), "sm": json.dumps(summary, default=str), "st": started,
         "en": now()})
    if drift:
        await s.rollback()
        raise RuntimeError(f"{VERSION}: {drift} stored rows differ from the recompute")
    await s.commit()
    return {"run_id": str(run_id), "label_version": VERSION, "cutoff": cutoff.isoformat(),
            "rows_sha256": rows_sha, "instruments": len(digests), "source_fingerprints": fps,
            **{k: v for k, v in summary.items() if k != "definition"}}
