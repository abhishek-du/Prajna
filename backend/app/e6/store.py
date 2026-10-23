"""E6 monitor I/O: reads results_event (OUTCOME, the live NSE announcements pipeline),
trading_session, instrument and canon_market_bar; writes only files under
var/research/e6 (append-only). PAPER RESEARCH ONLY."""

from __future__ import annotations

import datetime as _dt
import json
import statistics
import subprocess
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import now
from app.e6 import monitor as M

ENTRY_OPEN = _dt.time(9, 15)


def _freeze_path():
    return M.DIR / "freeze.json"


def load_freeze() -> dict[str, Any]:
    p = _freeze_path()
    if not p.exists():
        raise RuntimeError("E6 is not frozen: run `prajna e6 freeze --commit`")
    f = json.loads(p.read_text())
    if f["rule_sha256"] != M.RULE_SHA:
        raise RuntimeError(f"E6 rule changed after the freeze ({f['rule_sha256'][:12]} != "
                           f"{M.RULE_SHA[:12]}): a new pre-registration is needed")
    return f


def freeze(*, commit: bool) -> dict[str, Any]:
    p = _freeze_path()
    if p.exists():
        return {"status": "EXISTS", **json.loads(p.read_text())}
    root = M.DIR.parents[2]
    git = subprocess.run(["git", "rev-parse", "HEAD"],  # noqa: S607
                         capture_output=True, text=True, cwd=root).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain",  # noqa: S607
                            "--untracked-files=no"], capture_output=True, text=True,
                           cwd=root).stdout
    if dirty.strip():
        raise RuntimeError("the working tree is dirty; commit first")
    f = {"frozen_at": now().isoformat(), "rule": M.RULE, "rule_sha256": M.RULE_SHA,
         "code_git_sha": git}
    if commit:
        M.DIR.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(f, indent=1))
    return {"status": "FROZEN" if commit else "DRY_RUN", **f}


async def _sessions(s: AsyncSession, lo: _dt.date, hi: _dt.date) -> list[_dt.date]:
    return [r[0] for r in (await s.execute(text("""select session_date from trading_session
        where is_trading_day and session_date between :a and :b order by 1"""),
        {"a": lo, "b": hi})).all()]


async def _bars(s: AsyncSession, keys: list[str], lo: _dt.date, hi: _dt.date
                ) -> dict[str, dict[_dt.date, tuple[float, float, float]]]:
    """key -> date -> (open, close, traded value); bars knowable now."""
    out: dict[str, dict[_dt.date, tuple[float, float, float]]] = {}
    for k, d, o, c, v in (await s.execute(text("""select instrument_key, market_date, open,
            close, volume from canon_market_bar where timeframe = '1d'
            and instrument_key = any(:k) and market_date between :a and :b
            and knowable_at <= now()"""), {"k": keys, "a": lo, "b": hi})).all():
        out.setdefault(k, {})[d] = (float(o), float(c), float(c) * float(v or 0))
    return out


async def record(s: AsyncSession, *, commit: bool, at: _dt.datetime | None = None
                 ) -> dict[str, Any]:
    f = load_freeze()
    t = (at or now()).astimezone(M.IST)
    today = t.date()
    sess = await _sessions(s, today - _dt.timedelta(days=120), today + _dt.timedelta(days=10))
    if today not in sess:
        return {"status": "NOT_A_TRADING_DAY", "day": str(today)}
    if t.time() >= ENTRY_OPEN:
        return {"status": "TOO_LATE", "day": str(today),
                "note": "the entry is today's 09:15 open; a record after it is refused"}
    out_path = M.DIR / "signals" / f"{today}.jsonl"
    if out_path.exists():
        return {"status": "EXISTS", "file": str(out_path)}
    i = sess.index(today)
    d1, d0, dm1 = sess[i - 1], sess[i - 2], sess[i - 3]
    frozen_at = _dt.datetime.fromisoformat(f["frozen_at"])
    last = _dt.date.fromisoformat(M.RULE["window_last_event"])
    ev = (await s.execute(text("""select instrument_key, period_end, event_at from results_event
        where kind = 'OUTCOME' and event_at > :f and event_at < :hi order by event_at"""),
        {"f": frozen_at, "hi": _dt.datetime.combine(d0, _dt.time(23, 59), M.IST)})).all()
    seen: dict[str, _dt.date] = {}
    cands = []
    for k, pe, ea in ev:                              # chronological: the first filing wins
        if not k.startswith("NSE_EQ|"):
            continue
        z = M.day0(ea, sess)
        if z is None or ea.astimezone(M.IST).date() > last:
            continue
        if k in seen and (z - seen[k]).days <= M.RULE["dedupe_days"]:
            continue
        seen[k] = z
        lag = (ea.astimezone(M.IST).date() - pe).days if pe else None
        if z == d0 and (lag is None or 0 <= lag <= M.RULE["max_lag_days"]):
            cands.append({"key": k, "period_end": str(pe) if pe else None,
                          "event_at": ea.isoformat(), "lag_days": lag})
    keys = sorted({c["key"] for c in cands})
    active = {r[0] for r in (await s.execute(text("""select instrument_key from instrument
        where instrument_key = any(:k) and valid_to = 'infinity'
          and lifecycle_status = 'ACTIVE'"""), {"k": keys})).all()}
    j0 = sess.index(d0)
    hist = sess[max(0, j0 - 21):j0 - 1]               # the 20 sessions ending day -2
    bars = await _bars(s, [*keys, M.RULE["benchmark"]], hist[0] if hist else dm1, d1)
    bench = bars.get(M.RULE["benchmark"], {})
    rows = []
    for c in cands:
        b = bars.get(c["key"], {})
        r = {**c, "day0": str(d0), "day1": str(d1), "entry_day": str(today),
             "recorded_at": now().isoformat(), "rule_sha256": M.RULE_SHA}
        if c["key"] not in active:
            r.update(cls="EXCLUDED", reason="NOT_ACTIVE")
        elif not all(d in b for d in (dm1, d0, d1)) or not all(d in bench for d in (dm1, d0, d1)):
            r.update(cls="EXCLUDED", reason="BAR_MISSING")
        else:
            tv = [b[d][2] for d in hist if d in b]
            med = statistics.median(tv) if len(tv) >= 10 else None
            prev = b[dm1][1]
            r["car01"] = M.car01([b[d][1] for d in (dm1, d0, d1)],
                                 [bench[d][1] for d in (dm1, d0, d1)])
            r["prev_close"], r["median_tv"] = prev, med
            if prev < M.RULE["min_prev_close"]:
                r.update(cls="EXCLUDED", reason="PRICE")
            elif med is None or med < M.RULE["min_median_traded_value"]:
                r.update(cls="EXCLUDED", reason="TURNOVER")
            else:
                r["cls"] = M.classify(r["car01"])
        rows.append(r)
    res = {"status": "RECORDED" if commit else "DRY_RUN", "entry_day": str(today),
           "day0": str(d0), "events": len(cands),
           "by_class": {k: sum(r["cls"] == k for r in rows)
                        for k in ("PICK", "CONTROL", "OTHER", "EXCLUDED")}}
    if commit:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = out_path.with_suffix(".part")
        tmp.write_text("".join(json.dumps(r) + "\n" for r in rows))
        tmp.replace(out_path)
        res["file"] = str(out_path)
    return res


def load_rows() -> list[dict[str, Any]]:
    d = M.DIR / "signals"
    if not d.exists():
        return []
    return [json.loads(x) for p in sorted(d.glob("*.jsonl"))
            for x in p.read_text().splitlines() if x.strip()]


async def _evaluate(s: AsyncSession, rows: list[dict]) -> list[dict]:
    keys = sorted({r["key"] for r in rows if r["cls"] in ("PICK", "CONTROL")})
    if not keys:
        return []
    lo = min(_dt.date.fromisoformat(r["entry_day"]) for r in rows)
    sess = await _sessions(s, lo, lo + _dt.timedelta(days=400))
    bars = await _bars(s, [*keys, M.RULE["benchmark"]], lo, sess[-1])
    bench = bars.get(M.RULE["benchmark"], {})
    out = []
    for r in rows:
        if r["cls"] not in ("PICK", "CONTROL"):
            continue
        e = _dt.date.fromisoformat(r["entry_day"])
        i = sess.index(e)
        if i + M.RULE["hold_sessions"] - 1 >= len(sess):
            out.append({**r, "state": "OPEN"})
            continue
        x = sess[i + M.RULE["hold_sessions"] - 1]
        b = bars.get(r["key"], {})
        if not all(d in b and d in bench for d in (e, x)):
            out.append({**r, "state": "OPEN" if x >= now().astimezone(M.IST).date()
                        else "NOT_EVALUABLE"})
            continue
        out.append({**r, "state": "CLOSED", "entry": e, "exit": str(x),
                    **M.outcome(b[e][0], b[x][1], bench[e][0], bench[x][1])})
    return out


async def status(s: AsyncSession) -> dict[str, Any]:
    rows = load_rows()
    ev = await _evaluate(s, rows)
    st: dict[str, int] = {}
    for r in ev:
        st[f"{r['cls']}:{r['state']}"] = st.get(f"{r['cls']}:{r['state']}", 0) + 1
    try:
        f = load_freeze()
    except RuntimeError as e:
        return {"frozen": False, "error": str(e)}
    cal_end = (await s.execute(text("""select max(session_date) from trading_session"""))).scalar()
    return {"frozen": True, "frozen_at": f["frozen_at"], "rule": M.RULE["version"],
            "days_recorded": len({r["entry_day"] for r in rows}), "rows": len(rows),
            "by_class": {k: sum(r["cls"] == k for r in rows)
                         for k in ("PICK", "CONTROL", "OTHER", "EXCLUDED")},
            "evaluation_states": st, "calendar_ends": str(cal_end),
            "window_last_event": M.RULE["window_last_event"],
            "performance": "not shown before the look (single look at the end)"}


async def look(s: AsyncSession) -> dict[str, Any]:
    rows = load_rows()
    ev = await _evaluate(s, rows)
    last = _dt.date.fromisoformat(M.RULE["window_last_event"])
    if now().astimezone(M.IST).date() <= last:
        return {"status": "REFUSED", "reason": f"the window runs to {last}"}
    if any(r["state"] == "OPEN" for r in ev):
        return {"status": "REFUSED", "reason": "picks or controls still open"}
    ledger = M.DIR / "look.json"
    if ledger.exists():
        return {"status": "REFUSED", "reason": "the look was already taken",
                **json.loads(ledger.read_text())}
    closed = [r for r in ev if r["state"] == "CLOSED"]
    res = {"status": "LOOKED", "at": now().isoformat(), **M.look_stats(closed),
           "not_evaluable": sum(r["state"] == "NOT_EVALUABLE" for r in ev)}
    ledger.write_text(json.dumps(res, indent=1, default=str))
    return res
