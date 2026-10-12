"""E1 shadow log (approved 2026-10-12): LOGGING ONLY - no order, no broker call, no
database write (every read is REPEATABLE READ, READ ONLY). The logic is
app/training/shadow.py.

  freeze-weights   once: refit the E1 fold-4 ridge (TRAIN 2025-09-24..2026-07-20,
                   alpha 100, config 82e828c8...) and store it (refuses to overwrite)
  picks [--date D] 09:06 IST: universe, scores and picks from D's production
                   PRE_SESSION features; refused unless the features carry the active
                   registry; a file written at or after 09:15 IST is flagged LATE
  open  [--date D] 09:45 IST: real level-1 quotes at the open from the pre-open capture
  outcomes         every logged day before today whose canonical daily bars exist
  summary          the pooled E1 metrics over all days with outcomes (forward, strict)

Files: var/shadow/e1/<D>/{picks,open,outcomes}.json - each written once, never
overwritten; var/shadow/e1/ledger.jsonl records every write with its sha256.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import hashlib
import json
import pathlib
import sys
from typing import Any

import numpy as np
from sqlalchemy import text

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ops/measure"))

from app.core.clock import IST, now  # noqa: E402
from app.db.engine import get_sessionmaker  # noqa: E402
from app.features import registry as R  # noqa: E402
from app.training import e1 as E  # noqa: E402
from app.training import replay as RP  # noqa: E402
from app.training import shadow as SH  # noqa: E402

OUT = ROOT / "var/shadow/e1"
SEED = 20261012
E1_P2_CONFIG = "82e828c87e2a581048bac4a140c0e69c7e15056bd57ec4dd8324becfad2ad472"
P2_WINDOW = (_dt.date(2025, 9, 24), _dt.date(2026, 7, 20))
P2_ALPHA = 100.0
WAIT_UNTIL = _dt.time(9, 13)


def stamp() -> dict[str, Any]:
    code = RP.code_version()
    return {"written_at": now().astimezone(IST).isoformat(), "code_git_sha": code["git_sha"],
            "dirty": code["dirty"]}


def write_once(path: pathlib.Path, doc: dict[str, Any]) -> str:
    if path.exists():
        raise SystemExit(f"REFUSED: {path.relative_to(ROOT)} exists (written once)")
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(doc, indent=1, default=str)
    path.write_text(body)
    sha = hashlib.sha256(body.encode()).hexdigest()
    with (OUT / "ledger.jsonl").open("a") as f:
        f.write(json.dumps({"file": str(path.relative_to(OUT)), "sha256": sha,
                            **{k: doc.get(k) for k in ("phase", "session_date", "status",
                                                       "written_at", "code_git_sha")}},
                           default=str) + "\n")
    return sha


async def ro(s) -> None:
    await s.execute(text("set transaction isolation level repeatable read, read only"))


async def trading_day(s, d: _dt.date) -> bool:
    r = (await s.execute(text("""select is_trading_day and session_type = 'NORMAL'
        from trading_session where session_date = :d"""), {"d": d})).scalar()
    return bool(r)


# ── freeze-weights ─────────────────────────────────────────────────────────────────────
async def freeze_weights() -> dict[str, Any]:
    import stage4_e1_selection as X
    cfg = {"dataset": "stage4-ds-v3-asif", "label_version": "label-v2", "target": "ret_oc",
           "universe_top": 500}
    async with get_sessionmaker()() as s:
        await ro(s)
        days = list((await s.execute(text("""select session_date from training_session_done
            where dataset_version = :v and snapshot = 'PRE_SESSION'
              and session_date between :a and :b order by 1"""),
            {"v": cfg["dataset"], "a": P2_WINDOW[0], "b": P2_WINDOW[1]})).scalars())
        w = await X.fit_ridge(X.Loader(s, cfg), days, 500, P2_ALPHA)
        await s.rollback()
    return {"phase": "weights", "source_config_sha256": E1_P2_CONFIG, "fold": 4,
            "train_window": [str(d) for d in P2_WINDOW], "train_sessions": len(days),
            "alpha": P2_ALPHA, "features": list(E.CORE24), "weights": w.tolist(),
            "note": "E1 P2 was dropped (A5); logged for forward evidence only", **stamp()}


def load_weights() -> np.ndarray:
    p = OUT / "weights.json"
    if not p.exists():
        raise SystemExit("REFUSED: run freeze-weights first")
    d = json.loads(p.read_text())
    if d["features"] != list(E.CORE24):
        raise SystemExit("REFUSED: weights.json was frozen for another feature list")
    return np.array(d["weights"])


# ── picks ──────────────────────────────────────────────────────────────────────────────
async def feature_rows(s, d: _dt.date) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = [dict(r) for r in (await s.execute(text("""select instrument_key, feature_id,
            value, registry_sha256, as_of, run_id::text as run_id from feature_value
            where session_date = :d and snapshot = 'PRE_SESSION' and scope = 'INSTRUMENT'
              and instrument_key like 'NSE_EQ|%%' and feature_id = any(:ids)"""),
            {"d": d, "ids": list(E.CORE24)})).mappings().all()]
    meta = {"rows": len(rows),
            "registry_sha256": sorted({r["registry_sha256"] for r in rows}),
            "as_of": sorted({str(r["as_of"]) for r in rows}),
            "run_ids": sorted({r["run_id"] for r in rows})}
    return rows, meta


async def picks(d: _dt.date, w: np.ndarray) -> dict[str, Any]:
    async with get_sessionmaker()() as s:
        await ro(s)
        out = await picks_in(s, d, w)
        await s.rollback()
    return out


async def picks_in(s, d: _dt.date, w: np.ndarray) -> dict[str, Any]:
    """The picks document of session d, read through s (no write)."""
    if not await trading_day(s, d):
        return {"phase": "picks", "session_date": d, "status": "SKIP_NOT_NORMAL_SESSION"}
    rows, meta = await feature_rows(s, d)
    doc: dict[str, Any] = {"phase": "picks", "session_date": d, "snapshot": "PRE_SESSION",
                           "features": meta, "active_registry_sha256": R.REGISTRY_SHA256}
    if not rows:
        return {**doc, "status": "NO_FEATURES"}
    if meta["registry_sha256"] != [R.REGISTRY_SHA256]:
        return {**doc, "status": "REGISTRY_MISMATCH"}
    sess = SH.session_from_rows(rows)
    if sess is None:
        return {**doc, "status": "NO_ELIGIBLE"}
    return {**doc, "status": "OK", **SH.make_picks(sess, w)}


# ── open ───────────────────────────────────────────────────────────────────────────────
async def open_rows(s, d: _dt.date, keys: list[str]) -> list[dict[str, Any]]:
    return [{"key": r[0], "ist_time": r[1], "bid": r[2], "ask": r[3], "ltp": r[4]}
            for r in (await s.execute(text("""select t.instrument_key,
              (t.vendor_ts at time zone 'Asia/Kolkata')::time, b.bid_price, b.ask_price, t.ltp
            from preopen_tick t left join preopen_book b on b.tick_id = t.tick_id
              and b.rung_no = 1
            where t.session_date = :d and t.instrument_key = any(:k)
              and (t.vendor_ts at time zone 'Asia/Kolkata')::time between '09:15:00'
                  and '09:20:00'"""), {"d": d, "k": keys})).all()]


async def open_phase(d: _dt.date) -> dict[str, Any]:
    pk = OUT / str(d) / "picks.json"
    if not pk.exists():
        raise SystemExit(f"REFUSED: no picks file for {d}")
    p = json.loads(pk.read_text())
    if p["status"] != "OK":
        return {"phase": "open", "session_date": d, "status": f"SKIP_PICKS_{p['status']}"}
    keys = [u["key"] for u in p["universe"]]
    async with get_sessionmaker()() as s:
        await ro(s)
        rows = await open_rows(s, d, keys)
        await s.rollback()
    q = SH.open_quotes(rows)
    status = "OK" if q else "NO_DEPTH"
    picked = set(p["picks"]["p1_reversal"]) | set(p["picks"]["p2_ridge24"])
    spreads = [q[k]["first_spread_bps"] for k in picked
               if k in q and q[k]["first_spread_bps"] is not None]
    return {"phase": "open", "session_date": d, "status": status, "quotes": q,
            "universe_with_quote": sum(1 for k in keys if q.get(k, {}).get("first_bid")),
            "picks_median_first_spread_bps": float(np.median(spreads)) if spreads else None}


# ── outcomes ───────────────────────────────────────────────────────────────────────────
async def outcomes(today: _dt.date) -> list[dict[str, Any]]:
    done = []
    for pk in sorted(OUT.glob("*/picks.json")):
        d = _dt.date.fromisoformat(pk.parent.name)
        if d >= today or (pk.parent / "outcomes.json").exists():
            continue
        p = json.loads(pk.read_text())
        if p["status"] != "OK":
            continue
        keys = [u["key"] for u in p["universe"]]
        async with get_sessionmaker()() as s:
            await ro(s)
            bars = {r[0]: (r[1], r[2]) for r in (await s.execute(text("""select instrument_key,
                open, close from canon_market_bar where timeframe = '1d' and market_date = :d
                  and instrument_key = any(:k)"""), {"d": d, "k": keys})).all()}
            await s.rollback()
        if len(bars) < 0.5 * len(keys):
            continue                      # the canonical daily bars are not in yet
        y = {k: float(c) / float(o) - 1 for k, (o, c) in bars.items() if o and c and o > 0}
        doc = {"phase": "outcomes", "session_date": d, "status": "OK",
               "target": "open-to-close, canonical daily bar (gross)",
               "y": y, "metrics": SH.evaluate_day(p, y, seed=SEED, day=d)}
        write_once(pk.parent / "outcomes.json", {**doc, **stamp()})
        done.append({"session_date": str(d), "evaluable": doc["metrics"]["evaluable"]})
    return done


def summary() -> dict[str, Any]:
    out: dict[str, Any] = {"days": 0}
    per: dict[str, list[dict[str, Any]]] = {"p1_reversal": [], "p2_ridge24": []}
    for f in sorted(OUT.glob("*/outcomes.json")):
        m = json.loads(f.read_text())["metrics"]
        out["days"] += 1
        for name in per:
            r = dict(m[name])
            r["_universe_y"] = np.array([])
            r["_k"] = 0
            per[name].append(r)
    if out["days"] < 6:
        return {**out, "note": "fewer than 6 days with outcomes; no pooled statistics"}
    for name, rows in per.items():
        s = E.summarise(rows, [0] * len(rows), b=10000, block=5, level=0.975, seed=SEED,
                        perm_draws=1)
        out[name] = {k: v for k, v in s.items() if k not in ("c1", "daily_excess")}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=("freeze-weights", "picks", "open", "outcomes",
                                      "summary"))
    ap.add_argument("--date")
    a = ap.parse_args()
    today = now().astimezone(IST).date()
    d = _dt.date.fromisoformat(a.date) if a.date else today
    if a.phase == "summary":
        print(json.dumps(summary(), indent=1, default=str))
        return 0
    if RP.code_version()["dirty"]:
        raise SystemExit("REFUSED: the working tree is dirty; commit first")
    OUT.mkdir(parents=True, exist_ok=True)
    if a.phase == "freeze-weights":
        doc = asyncio.run(freeze_weights())
        sha = write_once(OUT / "weights.json", doc)
        print(json.dumps({"written": "weights.json", "sha256": sha,
                          "train_sessions": doc["train_sessions"]}, indent=1))
    elif a.phase == "picks":
        w = load_weights()
        doc = asyncio.run(picks(d, w))
        # live run: Stage 3 PRE_SESSION (cron 09:00:30) may still be committing
        while (not a.date and doc["status"] == "NO_FEATURES"
               and now().astimezone(IST).time() < WAIT_UNTIL):
            import time
            time.sleep(20)
            doc = asyncio.run(picks(d, w))
        doc.update(stamp())
        at = _dt.datetime.fromisoformat(doc["written_at"])
        doc["timing"] = ("ON_TIME" if at.date() == d and at.time() < SH.MARKET_OPEN
                         else "LATE (written at or after 09:15 IST of the session)")
        sha = write_once(OUT / str(d) / "picks.json", doc)
        print(json.dumps({"session_date": str(d), "status": doc["status"],
                          "timing": doc["timing"], "sha256": sha,
                          "universe": doc.get("universe_size"),
                          "picks": {k: len(v) for k, v in doc.get("picks", {}).items()}},
                         indent=1, default=str))
    elif a.phase == "open":
        doc = {**asyncio.run(open_phase(d)), **stamp()}
        sha = write_once(OUT / str(d) / "open.json", doc)
        print(json.dumps({"session_date": str(d), "status": doc["status"], "sha256": sha,
                          "universe_with_quote": doc.get("universe_with_quote"),
                          "picks_median_first_spread_bps":
                              doc.get("picks_median_first_spread_bps")}, indent=1))
    else:
        print(json.dumps({"outcomes_written": asyncio.run(outcomes(today))}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
