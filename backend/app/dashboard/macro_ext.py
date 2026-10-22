"""Non-Upstox macro series for the dashboard (user 2026-10-22: "FRED se US10Y aur DXY add
kar do"). DISPLAY ONLY: kept in memory, never written to the database, never a feature or
model input (Prajna's market data stays Upstox-only).

  US 10-year Treasury yield  U.S. Department of the Treasury, Daily Treasury Par Yield
                             Curve Rates (official, public domain; FRED's DGS10 is this
                             series). FRED's own CSV endpoint times out from this network.
  US dollar index            FRED DTWEXBGS, the Federal Reserve's Nominal Broad U.S. Dollar
                             Index (daily). It is NOT the ICE "DXY" (a proprietary index
                             not on FRED); shown under its own name. Needs FRED_API_KEY in
                             .env (free); without it the series is listed as not available.
Both are daily and published after the US day: they lag by about one day.
"""

from __future__ import annotations

import csv
import datetime as _dt
import io
import os
from typing import Any

import httpx

TREASURY = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
            "daily-treasury-rates.csv/{y}/all?type=daily_treasury_yield_curve"
            "&field_tdr_date_value={y}&page&_format=csv")
FRED = "https://api.stlouisfed.org/fred/series/observations"
TIMEOUT = 40.0


async def us10y(client: httpx.AsyncClient, today: _dt.date) -> dict[str, Any] | None:
    rows: list[tuple[_dt.date, float]] = []
    for y in {today.year, (today - _dt.timedelta(days=10)).year}:
        r = await client.get(TREASURY.format(y=y), timeout=TIMEOUT)
        r.raise_for_status()
        for row in csv.DictReader(io.StringIO(r.text)):
            try:
                rows.append((_dt.datetime.strptime(row["Date"], "%m/%d/%Y").date(),
                             float(row["10 Yr"])))
            except (KeyError, ValueError):
                continue
    rows.sort()
    if len(rows) < 2:
        return None
    (_, v0), (d1, v1) = rows[-2], rows[-1]
    return {"key": "EXT|US10Y", "name": "US 10-year yield (%)", "ltp": v1, "prev_close": v0,
            "change": None, "change_bps": round((v1 - v0) * 100, 1), "date": str(d1),
            "at": None, "unit": "%",
            "basis": "US Treasury daily par yield curve (official; = FRED DGS10), "
                     f"as of {d1}"}


async def broad_dollar(client: httpx.AsyncClient, today: _dt.date) -> dict[str, Any] | None:
    key = os.environ.get("FRED_API_KEY")
    if not key:
        return None
    r = await client.get(FRED, params={
        "series_id": "DTWEXBGS", "api_key": key, "file_type": "json",
        "observation_start": str(today - _dt.timedelta(days=30))}, timeout=TIMEOUT)
    r.raise_for_status()
    obs = [(o["date"], float(o["value"])) for o in r.json().get("observations", [])
           if o.get("value") not in (None, ".")]
    if len(obs) < 2:
        return None
    (_, v0), (d1, v1) = obs[-2], obs[-1]
    return {"key": "EXT|DTWEXBGS", "name": "US dollar index (Fed broad)", "ltp": v1,
            "prev_close": v0, "change": v1 / v0 - 1, "date": d1, "at": None,
            "basis": f"FRED DTWEXBGS (Federal Reserve nominal broad dollar index; not ICE "
                     f"DXY), as of {d1}"}


async def fetch(today: _dt.date) -> tuple[list[dict[str, Any]], list[str]]:
    """The series that could be read, and the names of those that could not."""
    got, missing = [], []
    async with httpx.AsyncClient(headers={"User-Agent": "Prajna-research/1.0"}) as c:
        for fn, name in ((us10y, "US 10-year Treasury yield"),
                         (broad_dollar, "US dollar index (FRED_API_KEY not set)"
                          if not os.environ.get("FRED_API_KEY") else "US dollar index")):
            try:
                x = await fn(c, today)
            except (httpx.HTTPError, ValueError, KeyError):
                x = None
            (got.append(x) if x else missing.append(name))
    return got, missing
