"""Operational status snapshot (hardening phase 4). Read-only.

One JSON document answering "is the live pipeline healthy right now?":
last run per job family, RUNNING runs and their age, who holds the candles
lock, the Upstox token's age, free disk, and the latest runbook log markers
(CLOSE_*, BACKFILL_*, GLOBAL_*, "done: <phase> fail=N"). Written daily to
var/status/ by cron, and printable on demand (`prajna ops status`).
"""

from __future__ import annotations

import datetime as _dt
import fcntl
import pathlib
import re
import shutil
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import IST, now

FAMILIES = {
    "instrument.refresh": "instrument.refresh", "security_class": "derive.security_class",
    "candles_1d": "ohlcv.1d.%", "candles_1m": "ohlcv.1m.%", "candles_15m": "ohlcv.15m.%",
    "candles_1h": "ohlcv.1h.%", "news": "news.%", "fii_dii": "macro.%",
    "corporate_actions": "corporate_action.%", "fundamentals": "fundamentals.%",
    "calendar": "calendar.%", "preopen": "preopen%", "stage2": "canon.process",
    "maintenance": "maint.%", "stage3": "features.%",
}
MARKERS = re.compile(r"(CLOSE_\w+|BACKFILL_\w+|GLOBAL_\w+|CLOSE_RERUN_CHECK|done: \w+.*fail=\d+"
                     r"|ABORT:.*|SKIP:.*)")


def lock_state(path: pathlib.Path) -> str:
    try:
        with open(path, "a") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return "HELD"
            fcntl.flock(f, fcntl.LOCK_UN)
            return "FREE"
    except OSError as e:
        return f"UNKNOWN ({e.__class__.__name__})"


def recent_markers(log_dir: pathlib.Path, n: int = 25) -> list[str]:
    files = sorted(log_dir.glob("*.log"), key=lambda p: p.stat().st_mtime)[-6:]
    out: list[str] = []
    for f in files:
        for line in f.read_text(errors="replace").splitlines():
            if MARKERS.search(line):
                out.append(f"{f.name}: {line.strip()[:220]}")
    return out[-n:]


async def snapshot(s: AsyncSession, base: pathlib.Path) -> dict[str, Any]:
    at = now()
    fam = {}
    for name, pattern in FAMILIES.items():
        r = (await s.execute(text("""
            select max(started_at), count(*) filter (where started_at > :d),
                   count(*) filter (where started_at > :d and status = 'FAILED'),
                   count(*) filter (where started_at > :d and status = 'ABORTED'),
                   count(*) filter (where started_at > :d and status = 'COMPLETE'),
                   count(*) filter (where status = 'RUNNING'),
                   count(*) filter (where finished_at > :d and status = 'ABORTED'
                                    and error like 'reaped by maint.reap_runs%')
            from ingest_run where stream like :p and mode = 'COMMIT'"""),
            {"p": pattern, "d": at - _dt.timedelta(hours=24)})).one()
        last = (await s.execute(text("""select status from ingest_run where stream like :p
            and mode = 'COMMIT' order by started_at desc limit 1"""), {"p": pattern})).scalar()
        fam[name] = {"last_started": r[0].astimezone(IST).isoformat() if r[0] else None,
                     "last_status": last, "runs_24h": r[1], "complete_24h": r[4],
                     "failed_24h": r[2], "aborted_24h": r[3], "running_now": r[5],
                     "reaped_24h": r[6]}
    running = (await s.execute(text("""select count(*), min(started_at) from ingest_run
        where status = 'RUNNING'"""))).one()
    tok = None
    try:
        from app.vendor.upstox.auth import load_cached
        rec = load_cached()
        if rec is not None:
            minted = getattr(rec, "minted_at", None)
            tok = {"minted_at": minted.astimezone(IST).isoformat() if minted else None,
                   "age_hours": round((at - minted).total_seconds() / 3600, 2) if minted else None,
                   "note": "Upstox tokens expire at ~03:30 IST"}
    except Exception as e:                       # status must never crash on a token problem
        tok = {"error": type(e).__name__}
    disk = shutil.disk_usage(base)
    return {
        "at": at.astimezone(IST).isoformat(),
        "families": fam,
        "running": {"count": running[0],
                    "oldest_age_hours": round((at - running[1]).total_seconds() / 3600, 2)
                    if running[1] else None},
        "candles_lock": lock_state(base / "var" / "run" / "candles.lock"),
        "upstox_token": tok,
        "disk_free_gb": round(disk.free / 1e9, 1),
        "recent_markers": recent_markers(base / "var" / "logs" / "daily"),
    }
