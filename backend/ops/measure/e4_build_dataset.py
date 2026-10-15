"""E4 step 2: the frozen intraday dataset (READ ONLY on the database; writes one file).

  .venv/bin/python ops/measure/e4_build_dataset.py --cutoff 2026-10-15T15:50:00+05:30 \
      [--from 2020-01-01] [--to 2026-10-14] [--out var/stage4/e4]

For every included NSE_EQ instrument: daily bars from pit.bars_adjusted at ONE recorded
knowledge cutoff, with allow_low_confidence=True (design A-1: before the corporate-action
horizon the vendor's own split/bonus adjustment is assumed; the result is labelled
VENDOR-BASIS). Sessions are the trading calendar's (trading_session), so a missing bar
is a NaN, never skipped. A RECONSTRUCTED bar is refused (never used).

Output (never overwritten):
  e4_daily_<cutoff>.npz       keys, sessions, open/high/low/close/volume [n_keys x n_days]
  e4_daily_<cutoff>.json      manifest: cutoff, range, counts, refused bars, content
                              sha256 (over the arrays, not the zip file), source
                              fingerprints, code sha
The open -> close label and the gap are computed from these arrays by app.training.e4;
nothing here is a performance metric.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import hashlib
import json
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from app.canon import pit  # noqa: E402
from app.db.engine import get_sessionmaker  # noqa: E402
from app.training import labels as L  # noqa: E402

FIELDS = ("open", "high", "low", "close", "volume")


def assemble(keys: list[str], days: list[_dt.date],
             rows_by_key: dict[str, list[dict]]) -> dict[str, np.ndarray]:
    """Pure: [n_keys x n_days] float64 matrices, NaN where a session has no bar."""
    idx = {d: i for i, d in enumerate(days)}
    out = {f: np.full((len(keys), len(days)), np.nan) for f in FIELDS}
    for j, k in enumerate(keys):
        for r in rows_by_key.get(k, []):
            i = idx.get(r["market_date"])
            if i is None:
                continue
            for f in FIELDS:
                if r.get(f) is not None:
                    out[f][j, i] = float(r[f])
    return out


def content_sha256(keys: list[str], days: list[_dt.date], arrays: dict[str, np.ndarray]) -> str:
    h = hashlib.sha256()
    h.update(json.dumps([keys, [str(d) for d in days]]).encode())
    for f in FIELDS:
        h.update(f.encode())
        h.update(np.ascontiguousarray(arrays[f], dtype="<f8").tobytes())
    return h.hexdigest()


async def build(start: _dt.date, end: _dt.date, cutoff: _dt.datetime) -> dict:
    async with get_sessionmaker()() as s:
        await s.execute(text("set transaction isolation level repeatable read, read only"))
        days = list((await s.execute(text("""select session_date from trading_session
            where is_trading_day and session_date between :a and :b order by 1"""),
            {"a": start, "b": end})).scalars())
        keys = list((await s.execute(text("""select instrument_key from canon_instrument
            where included and segment = 'NSE_EQ' order by 1"""))).scalars())
        rows, refused = {}, {"reconstructed": 0}
        for k in keys:
            r = await pit.bars_adjusted(s, k, "1d", cutoff, start=start, end=end,
                                        allow_low_confidence=True)
            rows[k] = r["rows"]
            refused["reconstructed"] += r["refused"]["reconstructed"]
        fps = await L.source_fingerprints(s, start, end, cutoff)
        await s.rollback()
    arrays = assemble(keys, days, rows)
    return {"keys": keys, "days": days, "arrays": arrays, "refused": refused,
            "source_fingerprints": fps,
            "bars": int(np.isfinite(arrays["close"]).sum())}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cutoff", required=True, type=_dt.datetime.fromisoformat)
    ap.add_argument("--from", dest="start", default="2020-01-01", type=_dt.date.fromisoformat)
    ap.add_argument("--to", dest="end", default="2026-10-14", type=_dt.date.fromisoformat)
    ap.add_argument("--out", default="var/stage4/e4")
    ap.add_argument("--verify-only", action="store_true",
                    help="rebuild and compare the content sha with the stored manifest")
    a = ap.parse_args()
    out = ROOT / a.out
    stem = f"e4_daily_{a.cutoff.strftime('%Y%m%dT%H%M%z')}"
    res = asyncio.run(build(a.start, a.end, a.cutoff))
    sha = content_sha256(res["keys"], res["days"], res["arrays"])
    if a.verify_only:
        stored = json.loads((out / f"{stem}.json").read_text())
        same = stored["content_sha256"] == sha
        print(json.dumps({"verify": "PASS" if same else "FAIL", "stored": stored["content_sha256"],
                          "rebuilt": sha}, indent=1))
        return 0 if same else 1
    out.mkdir(parents=True, exist_ok=True)
    npz, man = out / f"{stem}.npz", out / f"{stem}.json"
    if npz.exists() or man.exists():
        raise SystemExit(f"REFUSED: {npz.name} exists (frozen); use --verify-only")
    np.savez_compressed(npz, keys=np.array(res["keys"]),
                        sessions=np.array([str(d) for d in res["days"]]), **res["arrays"])
    from app.training import replay as RP
    manifest = {
        "dataset": "e4-daily-vendor-basis-v1", "cutoff": a.cutoff.isoformat(),
        "from": str(a.start), "to": str(a.end), "instruments": len(res["keys"]),
        "sessions": len(res["days"]), "bars": res["bars"], "refused": res["refused"],
        "basis": "pit.bars_adjusted, allow_low_confidence=True (VENDOR-BASIS, design A-1)",
        "content_sha256": sha, "file": npz.name,
        "file_sha256": hashlib.sha256(npz.read_bytes()).hexdigest(),
        "source_fingerprints": res["source_fingerprints"], "code": RP.code_version()}
    man.write_text(json.dumps(manifest, indent=1, default=str))
    print(json.dumps({k: v for k, v in manifest.items() if k != "source_fingerprints"},
                     indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
