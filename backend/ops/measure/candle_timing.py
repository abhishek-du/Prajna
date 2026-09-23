"""B1/B2 measurement poller. READ-ONLY for the database; archives everything.

    .venv/bin/python ops/measure/candle_timing.py --until "2026-09-24 17:30" \
        --key "NSE_EQ|INE002A01018" --key "NSE_EQ|INE040A01034" --key "NSE_INDEX|Nifty 50"

What it records, one JSON line per request, in var/measure/candle_timing_<start>.jsonl:
  B2  during the session (09:15-15:40 IST): intraday 1m every 6 s; 5m, 15m,
      1h and the intraday daily bar every 60 s. Tells when a closed bar first
      appears and whether it changes afterwards.
  B1  outside the session: the historical daily bars for the last few days,
      every 10 min (every 2 min for 15:30-17:30). Tells when a session's daily
      bar first appears on the historical endpoint and whether it is revised.

Every response goes through UpstoxRestClient (the shared rate limiter) and is
archived by PayloadStore before it is summarised. The token is re-read from
the cache every cycle: an expired token pauses polling (logged) until someone
logs in again, for example the pre-open runbook.
Run it as the only REST-heavy process (see vendor/upstox/rest.py).
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from app.contracts.candles import Window
from app.core.clock import IST, now
from app.core.config import get_settings
from app.core.errors import RateLimited, VendorAuthError, VendorError
from app.storage.payload_store import PayloadStore
from app.vendor.upstox.auth import load_cached
from app.vendor.upstox.rest import (
    UpstoxRestClient,
    historical_candle_path,
    intraday_candle_path,
)

SESSION = (_dt.time(9, 15), _dt.time(15, 40))
SLOW = ("5m", "15m", "1h", "1d")


def _summary(data: bytes) -> dict:
    try:
        body = json.loads(data)
        cs = body["data"]["candles"]
        return {"n": len(cs), "newest": cs[:3]}
    except Exception as e:                        # summary only; the bytes are archived
        return {"summary_error": repr(e)[:120]}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--until", required=True, help='"YYYY-MM-DD HH:MM" IST')
    ap.add_argument("--key", action="append", required=True)
    a = ap.parse_args()
    until = _dt.datetime.fromisoformat(a.until).replace(tzinfo=IST)
    store = PayloadStore(get_settings().archive_dir)
    out = pathlib.Path(get_settings().archive_dir).parent / "measure" / (
        f"candle_timing_{now().astimezone(IST):%Y%m%dT%H%M}.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    print(f"logging to {out}", flush=True)

    token, rest = None, None
    last_slow = last_b1 = 0.0
    loop = asyncio.get_running_loop()
    while now() < until:
        rec = load_cached()
        if rec is None or rec.access_token != token:
            if rest:
                await rest.aclose()
            token = rec.access_token if rec else None
            rest = UpstoxRestClient(token) if token else None
        t0, ist = loop.time(), now().astimezone(IST)
        in_session = SESSION[0] <= ist.time() < SESSION[1] and ist.weekday() < 5
        jobs: list[tuple[str, str, str]] = []
        if in_session:
            jobs += [("1m", k, intraday_candle_path(k, "1m")) for k in a.key]
            if t0 - last_slow >= 60:
                last_slow = t0
                jobs += [(tf + "_intraday", k, intraday_candle_path(k, tf))
                         for k in a.key for tf in SLOW]
        b1_every = 120 if _dt.time(15, 30) <= ist.time() < _dt.time(17, 30) else 600
        if t0 - last_b1 >= b1_every:
            last_b1 = t0
            w = Window(ist.date() - _dt.timedelta(days=4), ist.date())
            jobs += [("1d_hist", k, historical_candle_path(k, "1d", w)) for k in a.key]
        pause = 0
        for kind, key, path in jobs:
            line = {"kind": kind, "key": key, "req_at": now().isoformat()}
            if rest is None:
                line["error"] = "no token"
            else:
                try:
                    r = await rest.get(path)
                    sp = store.put(r.data, source="UPSTOX_REST_V3", ext="json",
                                   fetched_at=r.fetched_at)
                    line |= {"fetched_at": r.fetched_at.isoformat(), "status": r.status,
                             "sha": sp.sha256, "attempts": len(r.attempts), **_summary(r.data)}
                except (VendorAuthError, RateLimited, VendorError) as e:
                    line["error"] = f"{type(e).__name__}: {str(e)[:160]}"
            with out.open("a") as f:
                f.write(json.dumps(line) + "\n")
            err = line.get("error", "")
            if "RateLimited" in err:
                pause = 900                       # 15 min: never hammer a rate limit
                break
            if err == "no token" or "VendorAuthError" in err:
                pause = 300                       # wait for a fresh login
                break
        await asyncio.sleep(pause or (6 if in_session else 30))
    if rest:
        await rest.aclose()


if __name__ == "__main__":
    asyncio.run(main())
