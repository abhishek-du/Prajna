"""Research-only snapshot of Yahoo Finance analyst data for NSE stocks (user approval
2026-10-23: "approved yfinance research-only").

NOT a production source: nothing here writes the database, and nothing here is read by
Stage 3, Stage 4, the dashboard or any model. The output is append-only files under
var/research/yahoo/ for exploratory studies. PAPER RESEARCH ONLY; no order is placed.

Run with the separate research venv (backend/.venv-research, yfinance pinned), never the
production venv (the frozen E5 model depends on its packages):

    .venv-research/bin/python ops/research/yahoo_consensus.py UNIVERSE.csv OUT_DIR \
        [--only-covered COVERAGE.json] [--sleep 1.5] [--limit N]

UNIVERSE.csv: symbol,instrument_key (NSE symbols; ".NS" is appended).
Output: OUT_DIR/<date>.jsonl.gz, one line per symbol with fetched_at (the point-in-time
stamp: a value is knowable to Prajna only from fetched_at), the yfinance version, every
field as JSON (DataFrames as {columns, index, data}) and per-field errors; plus
OUT_DIR/<date>.manifest.json (counts, sha256) and OUT_DIR/coverage.json (symbols with any
analyst data, for the daily run). A file that exists is never overwritten.

Yahoo limits automated access (V1, 2026-08: once rate-limited it does not recover while
it is still hammered). Three consecutive rate-limit errors stop the run; it is recorded
as STOPPED and the next run starts over.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import hashlib
import json
import logging
import pathlib
import sys
import time
import warnings

import pandas as pd
import yfinance as yf

FIELDS = ("earnings_estimate", "revenue_estimate", "earnings_history", "eps_trend",
          "eps_revisions", "growth_estimates", "recommendations", "analyst_price_targets",
          "earnings_dates")
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def _plain(v):
    if isinstance(v, pd.DataFrame):
        d = v.reset_index()
        return {"columns": [str(c) for c in d.columns],
                "data": json.loads(d.to_json(orient="values", date_format="iso"))}
    if isinstance(v, dict):
        return {str(k): (None if pd.isna(x) else x) if isinstance(x, float) else x
                for k, x in v.items()}
    return v


def _rate_limited(e: Exception) -> bool:
    s = f"{type(e).__name__} {e}".lower()
    return "ratelimit" in s or "too many requests" in s or "429" in s


def covered(rec: dict) -> bool:
    ee = rec["fields"].get("earnings_estimate") or {}
    cols = ee.get("columns") or []
    if "numberOfAnalysts" in cols:
        j = cols.index("numberOfAnalysts")
        if any((r[j] or 0) > 0 for r in ee.get("data") or []):
            return True
    return bool((rec["fields"].get("recommendations") or {}).get("data"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("universe")
    ap.add_argument("out")
    ap.add_argument("--only-covered")
    ap.add_argument("--sleep", type=float, default=1.5)
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    warnings.filterwarnings("ignore")
    logging.disable(logging.CRITICAL)

    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    day = dt.datetime.now(IST).date().isoformat()
    path = out / f"{day}.jsonl.gz"
    if path.exists():
        print(json.dumps({"status": "EXISTS", "file": str(path)}))
        return 0
    uni = list(csv.DictReader(open(a.universe)))
    if a.only_covered:
        keep = set(json.loads(pathlib.Path(a.only_covered).read_text())["symbols"])
        uni = [u for u in uni if u["symbol"] in keep]
    if a.limit:
        uni = uni[:a.limit]

    tmp = path.with_suffix(".part")
    status, streak, n, cov, errs = "COMPLETE", 0, 0, [], 0
    with gzip.open(tmp, "wt") as fh:
        for u in uni:
            tk = yf.Ticker(u["symbol"] + ".NS")
            rec = {"symbol": u["symbol"], "instrument_key": u["instrument_key"],
                   "yfinance": yf.__version__, "fields": {}, "errors": {}}
            limited = False
            for f in FIELDS:
                try:
                    rec["fields"][f] = _plain(getattr(tk, f))
                except Exception as e:  # recorded per field
                    rec["errors"][f] = f"{type(e).__name__}: {str(e)[:200]}"
                    limited |= _rate_limited(e)
            rec["fetched_at"] = dt.datetime.now(dt.UTC).isoformat()
            streak = streak + 1 if limited else 0
            if streak >= 3:
                status = "STOPPED_RATE_LIMIT"
                break
            if limited:
                time.sleep(60)
                continue
            fh.write(json.dumps(rec, default=str) + "\n")
            n += 1
            errs += bool(rec["errors"])
            if covered(rec):
                cov.append(u["symbol"])
            time.sleep(a.sleep)
    tmp.replace(path)
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    man = {"day": day, "status": status, "universe": len(uni), "written": n,
           "with_errors": errs, "covered": len(cov), "file": path.name, "sha256": sha,
           "only_covered": bool(a.only_covered), "yfinance": yf.__version__,
           "note": "research only; knowable from fetched_at; not a production source"}
    (out / f"{day}.manifest.json").write_text(json.dumps(man, indent=1))
    if not a.only_covered and status == "COMPLETE":
        (out / "coverage.json").write_text(json.dumps({"as_of": day, "symbols": cov}))
    print(json.dumps(man))
    return 0 if status == "COMPLETE" else 1


if __name__ == "__main__":
    sys.exit(main())
