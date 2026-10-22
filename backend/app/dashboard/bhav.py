"""NSE's official closing prices for the dashboard (user 2026-10-22: REPL showed 78.69, the
last trade at the upper circuit, while NSE's official close was 77.68).

NSE's close is not the last trade: it is the weighted average of the last 30 minutes'
trades. After the session Upstox's quote holds the last trade for some names and the close
for others. So once NSE publishes the day's CM bhavcopy (public file, about 16:30 IST),
the dashboard shows its ClsPric as the price of every listed name, keyed by ISIN.

DISPLAY ONLY: never written to the database and never a feature or model input (stored
market data stays Upstox; the official daily bar arrives with the next morning's job).
"""

from __future__ import annotations

import csv
import datetime as _dt
import io
import zipfile
from typing import Any

import httpx

URL = ("https://nsearchives.nseindia.com/content/cm/"
       "BhavCopy_NSE_CM_0_0_0_{d:%Y%m%d}_F_0000.csv.zip")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"


def _f(x: str | None) -> float | None:
    try:
        return float(x) if x not in (None, "") else None
    except ValueError:
        return None


def parse(data: bytes, day: _dt.date) -> dict[str, dict[str, Any]]:
    """instrument_key (NSE_EQ|ISIN) -> the session's official prices."""
    z = zipfile.ZipFile(io.BytesIO(data))
    out = {}
    for r in csv.DictReader(io.TextIOWrapper(z.open(z.namelist()[0]), encoding="utf-8")):
        isin, cls = r.get("ISIN"), _f(r.get("ClsPric"))
        if not isin or cls is None or r.get("TradDt") not in (str(day), None, ""):
            continue
        prev = _f(r.get("PrvsClsgPric"))
        out[f"NSE_EQ|{isin}"] = {
            "symbol": r.get("TckrSymb"), "series": r.get("SctySrs"), "close": cls,
            "last": _f(r.get("LastPric")), "open": _f(r.get("OpnPric")),
            "high": _f(r.get("HghPric")), "low": _f(r.get("LwPric")), "prev_close": prev,
            "volume": _f(r.get("TtlTradgVol")), "date": str(day)}
    return out


async def fetch(day: _dt.date) -> dict[str, dict[str, Any]] | None:
    """The day's bhavcopy, or None while NSE has not published it."""
    async with httpx.AsyncClient(headers={"User-Agent": UA}, http2=False) as c:
        r = await c.get(URL.format(d=day), timeout=60.0)
    if r.status_code != 200 or not r.content.startswith(b"PK"):
        return None
    return parse(r.content, day)


def apply(q: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """A live quote with the official close in place of the last trade."""
    prev = b["prev_close"] or q.get("prev_close")
    return {**q, "ltp": b["close"], "last_trade": b["last"], "prev_close": prev,
            "open": b["open"] if b["open"] is not None else q.get("open"),
            "high": b["high"] if b["high"] is not None else q.get("high"),
            "low": b["low"] if b["low"] is not None else q.get("low"),
            "change": (b["close"] / prev - 1) if prev else q.get("change"),
            "official_close": True}
