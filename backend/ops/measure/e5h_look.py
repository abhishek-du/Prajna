"""E5-H single look: the frozen E5 model on every 2020 session (docs/STAGE4_E5H_PREREGISTRATION.md,
approved 2026-10-23). PAPER RESEARCH ONLY; read-only except the ledger/report files.

    .venv/bin/python ops/measure/e5h_look.py --check     # inputs only: counts, no outcome
    .venv/bin/python ops/measure/e5h_look.py --look      # the single look (refused twice)

Per session d of 2020 (the same machinery as `models report --look`):
  inputs   PRE_SESSION CORE24 values of dataset stage4-ds-h2020 (VALID), the 9 previous
           sessions as LSTM history (an absent one keeps its place); the frozen bundle
  excluded (pre-registered) instruments with a price-factor corporate action ex-date in
           (2026-09-23, the 2019 warm-up fetch]; for sessions to 2020-03-31 names whose first
           2020 open / last 2019 close moved > 25 % (the basis break)
  results  names with a results dissemination (F4 NSE filings) after the previous session's
           close and before d's open, or during d, are not selectable (E5's results-day rule)
  outcome  d's canonical daily bar (vendor-adjusted): ret_oc = close / open - 1 (as the E5
           forward look); masked: a locked bar (high = low or open <= 0), |close/prev close
           - 1| > 25 %, |open/prev close - 1| > 25 %
  metric   EV.session / EV.pooled (s_d vs matched controls, MIS costs, sign-flip CI 0.975),
           placebo with random picks; gates A1-A4.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import hashlib
import json
import pathlib
import subprocess
import sys

import numpy as np
from sqlalchemy import text

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.core.clock import IST, now  # noqa: E402
from app.db.engine import get_sessionmaker  # noqa: E402
from app.models import data as D  # noqa: E402
from app.models import evaluate as EV  # noqa: E402
from app.models import forward as F  # noqa: E402
from app.models import recipe as R  # noqa: E402

DATASET = "stage4-ds-h2020"
FIRST, LAST = _dt.date(2020, 1, 1), _dt.date(2020, 12, 31)
BASIS_FROM = _dt.datetime(2026, 9, 23, tzinfo=IST)
BASIS_CHECK_UNTIL = _dt.date(2020, 3, 31)
EXTREME = 0.25
OUT = ROOT / "var/stage4/experiments/e5h"
PREREG = ROOT.parent / "docs/STAGE4_E5H_PREREGISTRATION.md"


async def h_session(s, day: _dt.date) -> D.Session | None:
    rows = (await s.execute(text(f"""
        select instrument_key, {D._COLS} from training_feature_value
         where dataset_version = :v and snapshot = 'PRE_SESSION' and session_date = :d
           and status = 'VALID' and feature_id = any(:ids) and instrument_key like 'NSE_EQ|%%'
         group by 1 order by 1"""),  # noqa: S608
        {"v": DATASET, "d": day, "ids": list(D.CORE)})).mappings().all()
    rows = [r for r in rows if all(r[f"f{i}"] is not None for i in range(len(D.CORE)))]
    if not rows:
        return None
    keys, X, y, masked = D._pivot(rows)
    return D.Session(day, keys, X, y, masked, DATASET)


def drop(sess: D.Session, bad: set[str]) -> D.Session:
    keep = [i for i, k in enumerate(sess.keys) if k not in bad]
    return D.Session(sess.date, [sess.keys[i] for i in keep], sess.X[keep],
                     {k: v[keep] for k, v in sess.y.items()}, sess.masked[keep], sess.source)


async def exclusions(s, warmup_fetch: _dt.datetime) -> tuple[set[str], set[str]]:
    ca = set((await s.execute(text("""select distinct instrument_key from canon_corporate_action
        where ex_date > :a and ex_date <= :b and action_type in ('SPLIT', 'BONUS', 'RIGHTS')"""),
        {"a": BASIS_FROM.date(), "b": warmup_fetch.date()})).scalars())
    brk = set((await s.execute(text("""
        with l as (select distinct on (instrument_key) instrument_key, close from canon_market_bar
                    where timeframe = '1d' and market_date <= '2019-12-31'
                      and instrument_key like 'NSE_EQ|%%'
                    order by instrument_key, market_date desc),
             f as (select distinct on (instrument_key) instrument_key, open from canon_market_bar
                    where timeframe = '1d' and market_date >= '2020-01-01'
                      and instrument_key like 'NSE_EQ|%%' order by instrument_key, market_date)
        select l.instrument_key from l join f using (instrument_key)
         where l.close > 0 and abs(f.open / l.close - 1) > :x"""), {"x": EXTREME})).scalars())
    return ca, brk


async def results_names(s, day: _dt.date, prev: _dt.date) -> set[str]:
    cal = {r[0]: (r[1], r[2]) for r in (await s.execute(text("""select session_date, close_ist,
        close_ist from trading_session where session_date in (:a, :b)"""),
        {"a": prev, "b": day})).all()}
    # after the previous session's close, up to d's close: the dissemination date stands
    # for the results meeting date, which listed companies announce days in advance (the
    # live rule reads those intimations); no time of day after the prediction is used
    lo = _dt.datetime.combine(prev, cal[prev][1], tzinfo=IST)
    hi = _dt.datetime.combine(day, cal[day][1], tzinfo=IST)
    return set((await s.execute(text("""select distinct instrument_key from results_event
        where kind = 'HISTORICAL_FILING' and event_at > :lo and event_at <= :hi"""),
        {"lo": lo, "hi": hi})).scalars())


async def outcomes(s, day: _dt.date, prev: _dt.date, keys: list[str]) -> dict[str, tuple]:
    rows = (await s.execute(text("""select instrument_key, market_date, open, high, low, close
        from canon_market_bar where timeframe = '1d' and instrument_key = any(:k)
          and market_date in (:p, :d)"""), {"k": keys, "p": prev, "d": day})).all()
    by: dict[str, dict] = {}
    for k, d, o, h, lo, c in rows:
        by.setdefault(k, {})[d] = (float(o), float(h), float(lo), float(c))
    return {k: (v[day], v.get(prev)) for k, v in by.items() if day in v}


def _git() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,  # noqa: S607
                          text=True, cwd=ROOT).stdout.strip()


async def run(look: bool) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    ledger = OUT / "ledger.json"
    if look and ledger.exists():
        return {"status": "REFUSED", "reason": "the E5-H look was already taken",
                **json.loads(ledger.read_text())}
    async with get_sessionmaker()() as s:
        sha, b = await F.load_model(s, None)
        days = [r[0] for r in (await s.execute(text("""select session_date from trading_session
            where is_trading_day and session_date between :a and :b order by 1"""),
            {"a": FIRST - _dt.timedelta(days=30), "b": LAST})).all()]
        test_days = [d for d in days if d >= FIRST]
        warm = (await s.execute(text("""select max(fetched_at) from canon_market_bar
            where timeframe = '1d' and market_date between '2019-09-01' and '2019-12-31'
              and instrument_key like 'NSE_EQ|%%'"""))).scalar()
        if warm is None:
            return {"status": "REFUSED", "reason": "the 2019 warm-up bars are not loaded"}
        ca_bad, brk_bad = await exclusions(s, warm)
        cache: dict[_dt.date, D.Session | None] = {}

        async def get(d):
            if d not in cache:
                x = await h_session(s, d)
                early = brk_bad if d <= BASIS_CHECK_UNTIL else set()
                cache[d] = None if x is None else drop(x, ca_bad | early)
            return cache[d]

        check = {"model_sha256": sha, "dataset": DATASET, "test_sessions": len(test_days),
                 "with_inputs": 0, "history_missing_total": 0,
                 "excluded_corporate_action": len(ca_bad), "excluded_basis_break": len(brk_bad),
                 "warmup_fetched_at": warm.isoformat()}
        per, placebo, not_evaluable = [], [], []
        rng = np.random.default_rng(R.SEED)
        for d in test_days:
            cur = await get(d)
            i = days.index(d)
            if cur is None:
                not_evaluable.append({"session": str(d), "reason": "no usable PRE_SESSION values"})
                continue
            check["with_inputs"] += 1
            hist = []
            for h in days[max(0, i - (D.SEQ_LEN - 1)):i]:
                x = await get(h)
                if x is None:
                    check["history_missing_total"] += 1
                    x = D.empty_session(h)
                hist.append(x)
            if not look:
                continue
            panel = [*hist, cur]
            out = R.predict(b, panel, len(panel) - 1)
            prev = days[i - 1]
            today = await results_names(s, d, prev)
            picks = R.select(out, b.cost, results_today=today)
            oc = await outcomes(s, d, prev, out["keys"])
            y = {lb: np.full(len(cur.keys), np.nan) for lb in D.LABELS}
            masked = np.zeros(len(cur.keys), dtype=bool)
            pos = {k: j for j, k in enumerate(cur.keys)}
            for k, ((o, h, lo, c), pv) in oc.items():
                j = pos[k]
                pc = pv[3] if pv else None
                if o <= 0 or h <= lo or (pc and (abs(c / pc - 1) > EXTREME
                                                 or abs(o / pc - 1) > EXTREME)):
                    masked[j] = True
                    continue
                y["ret_oc"][j] = c / o - 1
                y["high_exc"][j], y["low_exc"][j] = h / o - 1, lo / o - 1
            sess = D.Session(d, cur.keys, cur.X, y, masked, "e5h")
            per.append(EV.session(sess, out, picks, b.cost, seed=R.SEED))
            n = len(out["keys"])
            pl = sorted(rng.choice(n, size=min(len(picks), n), replace=False).tolist())
            placebo.append(EV.session(sess, out, pl, b.cost, seed=R.SEED + 1))
        if not look:
            return {"status": "CHECK", **check, "not_evaluable": not_evaluable[:20],
                    "note": "inputs only; no outcome was read"}
    pooled, pp = EV.pooled(per, seed=R.SEED), EV.pooled(placebo, seed=R.SEED)
    stress = [p["p_gross"] - 1.5 * p["p_cost"] - p["c2_gross"] for p in per
              if p.get("s") is not None]
    s_ = [p["s"] for p in per if p.get("s") is not None]
    half = len(s_) // 2
    gates = {"A1_ci_above_zero": bool(pooled.get("s_ci") and pooled["s_ci"][0] > 0),
             "A2_stress_mean_ge_zero": bool(stress) and float(np.mean(stress)) >= 0,
             "A3_both_halves_positive": bool(half) and float(np.mean(s_[:half])) > 0
             and float(np.mean(s_[half:])) > 0,
             "A4_placebo_ci_contains_zero": bool(pp.get("s_ci"))
             and pp["s_ci"][0] <= 0 <= pp["s_ci"][1]}
    rep = {"experiment": "E5-H", "at": now().isoformat(), "model_sha256": sha,
           "prereg_sha256": hashlib.sha256(PREREG.read_bytes()).hexdigest(),
           "code_git_sha": _git(), "check": check, "pooled": pooled, "placebo": pp,
           "stress_mean": float(np.mean(stress)) if stress else None, "gates": gates,
           "verdict": "ACCEPTED-HISTORICAL" if all(gates.values()) else "NOT_ACCEPTED",
           "not_evaluable_sessions": not_evaluable, "per_session": per,
           "note": "PAPER ONLY; AS_IF vendor-adjusted 2020 history; survivorship stated"}
    (OUT / "look.json").write_text(json.dumps(rep, indent=1, default=str) + "\n")
    ledger.write_text(json.dumps({k: rep[k] for k in ("at", "model_sha256", "prereg_sha256",
                                                      "code_git_sha", "verdict")}))
    return rep


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--look", action="store_true")
    a = ap.parse_args()
    out = asyncio.run(run(a.look))
    slim = {k: v for k, v in out.items() if k != "per_session"}
    print(json.dumps(slim, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
