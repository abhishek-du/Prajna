"""Live quotes for the dashboard (user 2026-10-22: "sab live hona chaiye").

A background poller in the dashboard process reads Upstox /v2/market-quote/quotes for
every active NSE instrument (500 keys a request): every 30 s from 09:00 to 15:45 IST on a
trading day, every 20 min otherwise (so the day's close shows as soon as the session
ends, not with the next morning's daily bar). READ-ONLY market data: no order API is ever
called. The quotes are DISPLAY ONLY - kept in memory, never written to the database, never
an input of a feature or a model (those stay point in time).

The cached Upstox token is used as it is; the dashboard never logs in. A missing or
rejected token shows "live unavailable" and the pages fall back to stored bars.
Its own conservative limiter (well inside Upstox's 50/s, 500/min, 2000/30 min per API).
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import json
import logging
from typing import Any

from app.core.clock import IST, now

log = logging.getLogger("dashboard.live")
MARKET_FROM, MARKET_TO = _dt.time(9, 0), _dt.time(15, 45)
FAST_S, SLOW_S = 30.0, 1200.0
LIMITS = ((4, 1.0), (120, 60.0), (1500, 1800.0))
# Global and BSE quotes (Upstox serves these through the same quote API); the commodity /
# currency indicators only as intraday candles (the quote API refuses their keys).
GLOBAL_QUOTES = {"GLOBAL_INDEX|SGX NIFTY": "GIFT Nifty", "BSE_INDEX|SENSEX": "Sensex",
                 "GLOBAL_INDEX|^GSPC": "S&P 500", "GLOBAL_INDEX|^DJI": "Dow Jones",
                 "GLOBAL_INDEX|IXIX": "US Tech 100", "GLOBAL_INDEX|DOW FUTURES": "US 30 futures",
                 "GLOBAL_INDEX|^N225": "Nikkei 225", "GLOBAL_INDEX|^HSI": "Hang Seng",
                 "GLOBAL_INDEX|^FTSE": "FTSE 100", "GLOBAL_INDEX|^GDAXI": "DAX",
                 "GLOBAL_INDEX|^FCHI": "CAC 40"}
INDICATORS = {"GLOBAL_INDICATOR|BZUSD": "Brent crude ($)", "GLOBAL_INDICATOR|CLUSD":
              "WTI crude ($)", "GLOBAL_INDICATOR|USDINR": "USD / INR"}
INDICATOR_EVERY_S = 300.0
EXT_EVERY_S = 3 * 3600.0           # US Treasury 10Y / FRED dollar index: daily series


class LiveQuotes:
    def __init__(self) -> None:
        self.quotes: dict[str, dict[str, Any]] = {}
        self.fetched_at: _dt.datetime | None = None
        self.status = "starting"
        self.error: str | None = None
        self.cycles = 0
        self._keys: list[str] = []
        self._keys_day: _dt.date | None = None
        self._trading: dict[_dt.date, bool] = {}
        self._task: asyncio.Task | None = None
        self.history: dict[str, list] = {}
        self._history_day: _dt.date | None = None
        self.indicators: dict[str, dict[str, Any]] = {}    # live Stage 3 price features
        self.globals: dict[str, dict[str, Any]] = {}       # global / BSE / commodity / FX
        self._indicator_at = 0.0
        self._prev_close: dict[str, float] = {}
        self._ext_at = -1e9
        self.ext_missing: list[str] = ["US 10-year Treasury yield", "US dollar index"]
        self._ext_keys: list[str] = []

    # ── public ──────────────────────────────────────────────────────────────────
    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    def get(self, key: str) -> dict[str, Any] | None:
        q = self.quotes.get(key)
        return q if q and self.fresh_for_today(q) else None

    @staticmethod
    def fresh_for_today(q: dict[str, Any]) -> bool:
        return q.get("date") == str(now().astimezone(IST).date())

    def global_view(self) -> list[dict[str, Any]]:
        order = [*GLOBAL_QUOTES, *INDICATORS, *self._ext_keys]
        return [self.globals[k] for k in order if k in self.globals]

    def summary(self) -> dict[str, Any]:
        return {"status": self.status, "error": self.error, "quotes": len(self.quotes),
                "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
                "cycles": self.cycles, "source": "Upstox market quote (display only)"}

    # ── loop ────────────────────────────────────────────────────────────────────
    async def _run(self) -> None:
        while True:
            fast = False
            try:
                fast = await self._in_market()
                await self._cycle()
                self.status = "live" if fast else "after-hours"
                self.error = None
            except asyncio.CancelledError:
                raise
            except Exception as e:                    # shown on the page; retried later
                self.status, self.error = "unavailable", f"{type(e).__name__}: {e}"[:200]
                log.warning("live quotes: %s", self.error)
            await asyncio.sleep(FAST_S if fast else SLOW_S)

    async def _in_market(self) -> bool:
        t = now().astimezone(IST)
        if not (MARKET_FROM <= t.time() <= MARKET_TO):
            return False
        return await self._trading_day(t.date())

    async def _trading_day(self, d: _dt.date) -> bool:
        if d not in self._trading:
            from sqlalchemy import text

            from app.db.engine import get_sessionmaker
            async with get_sessionmaker()() as s:
                self._trading[d] = bool((await s.execute(text(
                    "select is_trading_day from trading_session where session_date = :d"),
                    {"d": d})).scalar())
                await s.rollback()
        return self._trading[d]

    async def _load_keys(self) -> list[str]:
        today = now().astimezone(IST).date()
        if self._keys_day != today:
            from sqlalchemy import text

            from app.db.engine import get_sessionmaker
            async with get_sessionmaker()() as s:
                self._keys = list((await s.execute(text("""select instrument_key
                    from canon_instrument where included and lifecycle_status = 'ACTIVE'
                      and segment in ('NSE_EQ', 'NSE_INDEX') order by 1"""))).scalars())
                await s.rollback()
            self._keys_day = today
        return self._keys

    async def _cycle(self) -> None:
        from app.vendor.upstox.auth import load_cached
        from app.vendor.upstox.rest import (
            QUOTE_MAX_KEYS,
            RateLimiter,
            UpstoxRestClient,
            quotes_path,
        )
        rec = load_cached()
        if rec is None:
            raise RuntimeError("no cached Upstox token (the dashboard never logs in)")
        keys = await self._load_keys()
        c = UpstoxRestClient(rec.access_token, limiter=_limiter(RateLimiter))
        try:
            got: dict[str, dict[str, Any]] = {}
            for i in range(0, len(keys), QUOTE_MAX_KEYS):
                r = await c.get(quotes_path(keys[i:i + QUOTE_MAX_KEYS]))
                d = json.loads(r.data)
                if r.status != 200 or d.get("status") != "success":
                    raise RuntimeError(f"quotes HTTP {r.status} {list(r.error_codes)}")
                for v in (d.get("data") or {}).values():
                    q = parse(v)
                    if q:
                        got[q["key"]] = q
            await self._globals(c, quotes_path)
        finally:
            await c.aclose()
        self.quotes.update(got)
        self.fetched_at = now()
        await self._indicators()
        self.cycles += 1

    async def _globals(self, c, quotes_path) -> None:
        """Global indices and Sensex from quotes; Brent / WTI / USD-INR from intraday
        30-minute candles every INDICATOR_EVERY_S. Display only. A failure here never
        stops the NSE quotes."""
        import time

        from app.vendor.upstox.rest import _key
        try:
            r = await c.get(quotes_path(list(GLOBAL_QUOTES)))
            for v in (json.loads(r.data).get("data") or {}).values():
                q = parse(v)
                if q and q["key"] in GLOBAL_QUOTES:
                    self.globals[q["key"]] = {**q, "name": GLOBAL_QUOTES[q["key"]],
                                              "basis": "live quote"}
        except Exception as e:
            log.warning("global quotes: %s", e)
        if time.monotonic() - self._ext_at >= EXT_EVERY_S:
            self._ext_at = time.monotonic()
            from app.dashboard import macro_ext as MX
            try:
                got, self.ext_missing = await MX.fetch(now().astimezone(IST).date())
                for g in got:
                    self.globals[g["key"]] = g
                self._ext_keys = [g["key"] for g in got]
            except Exception as e:                    # shown as missing, never fatal
                log.warning("external macro: %s", e)
        if time.monotonic() - self._indicator_at < INDICATOR_EVERY_S:
            return
        self._indicator_at = time.monotonic()
        today = now().astimezone(IST).date()
        if getattr(self, "_prev_day", None) != today:
            self._prev_close = await _prev_daily_close(list(INDICATORS))
            self._prev_day = today
        for k, name in INDICATORS.items():
            try:
                r = await c.get(f"/v3/historical-candle/intraday/{_key(k)}/minutes/30")
                cs = (json.loads(r.data).get("data") or {}).get("candles") or []
                if not cs:
                    continue
                last = cs[0]                          # newest first
                at = _dt.datetime.fromisoformat(last[0])
                prev = self._prev_close.get(k)
                self.globals[k] = {"key": k, "name": name, "ltp": float(last[4]),
                                   "prev_close": prev,
                                   "change": (float(last[4]) / prev - 1) if prev else None,
                                   "at": at.isoformat(), "date": str(at.date()),
                                   "basis": "intraday 30-min candle"}
            except Exception as e:
                log.warning("indicator %s: %s", k, e)

    async def _indicators(self) -> None:
        """Stage 3's price features with today's live bar (indicators.py), off the loop."""
        from app.dashboard import indicators as IND
        today = now().astimezone(IST).date()
        if self._history_day != today:
            from app.db.engine import get_sessionmaker
            async with get_sessionmaker()() as s:
                await s.execute(__import__("sqlalchemy").text("set transaction read only"))
                self.history = await IND.load_history(s, today)
                await s.rollback()
            self._history_day = today
        fresh = {k: q for k, q in self.quotes.items() if self.fresh_for_today(q)}
        self.indicators = await asyncio.to_thread(IND.compute_all, self.history, fresh)


async def _prev_daily_close(keys: list[str]) -> dict[str, float]:
    """The latest stored daily close before today (raw ohlcv_bar: the canonical global
    view waits for finality, days later)."""
    from sqlalchemy import text

    from app.db.engine import get_sessionmaker
    today = now().astimezone(IST).date()
    async with get_sessionmaker()() as s:
        rows = (await s.execute(text("""select distinct on (i.instrument_key) i.instrument_key,
            b.close from ohlcv_bar b join instrument i using (instrument_id)
            where i.instrument_key = any(:k) and b.timeframe = '1d' and b.session_date < :d
            order by i.instrument_key, b.session_date desc, b.fetched_at desc"""),
            {"k": keys, "d": today})).all()
        await s.rollback()
    return {k: float(c) for k, c in rows}


_LIMITER = None


def _limiter(cls):
    global _LIMITER
    if _LIMITER is None:
        _LIMITER = cls(LIMITS)
    return _LIMITER


def parse(v: dict[str, Any]) -> dict[str, Any] | None:
    """One quote -> {key, ltp, open, high, low, prev_close, change, volume, at, date}."""
    key, ltp = v.get("instrument_token"), v.get("last_price")
    if not key or ltp is None:
        return None
    o = v.get("ohlc") or {}
    nc = v.get("net_change")
    prev = (ltp - nc) if nc is not None else None
    ts = v.get("last_trade_time")
    try:
        at = _dt.datetime.fromtimestamp(int(ts) / 1000, _dt.UTC) if ts else None
    except (TypeError, ValueError):
        at = None
    day = (at or now()).astimezone(IST).date()
    return {"key": key, "ltp": float(ltp), "open": o.get("open"), "high": o.get("high"),
            "low": o.get("low"), "prev_close": prev,
            "change": (ltp / prev - 1) if prev else None, "volume": v.get("volume"),
            "lower_circuit": v.get("lower_circuit_limit"),
            "upper_circuit": v.get("upper_circuit_limit"),
            "at": at.isoformat() if at else None, "date": str(day)}


def overlay(rec: dict[str, Any], q: dict[str, Any] | None) -> dict[str, Any]:
    """A market/stock row with the live quote applied (a copy)."""
    if not q:
        return rec
    out = dict(rec)
    out.update(close=q["ltp"], day_change=q["change"], close_date=q["date"], price_at=q["at"],
               price_basis="live (Upstox quote)")
    return out
