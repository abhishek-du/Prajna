"""Read-only fingerprints of production feature_value, per (session, snapshot):
row count, registry hashes, and an md5 over every row's identity and value.

  .venv/bin/python ops/measure/feature_fingerprint.py [--out FILE]
  .venv/bin/python ops/measure/feature_fingerprint.py --compare BEFORE AFTER [--expect-new D,...]

--compare exits 1 unless every (session, snapshot) present BEFORE is byte-identical
AFTER and the only new sessions are the expected ones. READ ONLY (repeatable read,
read only transaction).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from app.db.engine import get_sessionmaker  # noqa: E402

SQL = """select session_date::text, snapshot, count(*),
  array_agg(distinct registry_sha256 order by registry_sha256),
  md5(string_agg(md5(instrument_key || feature_id || feature_version::text
        || coalesce(value::text, '') || coalesce(reason, '') || inputs_sha256
        || registry_sha256), '' order by instrument_key, feature_id, feature_version))
from feature_value group by 1, 2 order by 1, 2"""


async def fingerprint() -> dict[str, dict]:
    async with get_sessionmaker()() as s:
        await s.execute(text("set transaction isolation level repeatable read, read only"))
        rows = (await s.execute(text(SQL))).all()
        await s.rollback()
    return {f"{d} {k}": {"rows": n, "registries": [r[:12] for r in regs], "md5": h}
            for d, k, n, regs, h in rows}


def compare(before: dict, after: dict, expect_new: set[str]) -> list[str]:
    bad = [f"CHANGED {k}" for k in before if after.get(k) != before[k]]
    new = {k.split()[0] for k in after if k not in before}
    if new != expect_new:
        bad.append(f"NEW SESSIONS {sorted(new)} != expected {sorted(expect_new)}")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    ap.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"))
    ap.add_argument("--expect-new", default="")
    a = ap.parse_args()
    if a.compare:
        b, f = (json.loads(pathlib.Path(p).read_text()) for p in a.compare)
        bad = compare(b, f, {x for x in a.expect_new.split(",") if x})
        print(json.dumps({"ok": not bad, "problems": bad,
                          "unchanged": sum(1 for k in b if f.get(k) == b[k]),
                          "new": sorted(k for k in f if k not in b)}, indent=1))
        return 0 if not bad else 1
    fp = asyncio.run(fingerprint())
    body = json.dumps(fp, indent=1, sort_keys=True)
    if a.out:
        pathlib.Path(a.out).write_text(body)
    print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
