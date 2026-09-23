"""The shared Upstox REST client. Offline: fake clock, mocked transport."""

from __future__ import annotations

import asyncio
import datetime as _dt
import json
import random

import httpx
import pytest

from app.contracts.candles import M4_TIMEFRAMES, Window, plan_windows
from app.core.errors import RateLimited, VendorAuthError, VendorError
from app.sources.upstox_calendar import UpstoxCalendarClient
from app.vendor.upstox import rest as R

TOKEN = "tok-SECRET-123"
D = _dt.date


class FakeClock:
    def __init__(self):
        self.t = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.t

    async def sleep(self, s: float) -> None:
        self.slept.append(s)
        self.t += s


def _limiter(clock, windows=None):
    return R.RateLimiter(windows, clock=clock, sleep=clock.sleep)


# ── limiter ─────────────────────────────────────────────────────────────────
class TestLimiter:
    def test_defaults_are_90_percent_of_the_documented_limits(self):
        assert R.DOCUMENTED_LIMITS == ((50, 1.0), (500, 60.0), (2000, 1800.0))
        assert R.default_windows() == ((45, 1.0), (450, 60.0), (1800, 1800.0))
        assert "suspension" in R.LIMITS_BASIS

    async def test_per_second_window(self):
        c = FakeClock()
        lim = _limiter(c)
        for _ in range(45):
            assert await lim.acquire() == 0.0
        waited = await lim.acquire()                 # the 46th in the same second
        assert waited == pytest.approx(1.001) and lim.count_in(1.0) <= 45   # +1 ms guard

    async def test_per_minute_window(self):
        c = FakeClock()
        lim = _limiter(c)
        for _ in range(450):
            await lim.acquire()
        t0 = c.t
        await lim.acquire()                          # the 451st
        assert c.t - 1000.0 >= 60.0 and lim.count_in(60.0) <= 450
        assert c.t > t0

    async def test_per_30_minutes_window(self):
        c = FakeClock()
        lim = _limiter(c)
        for _ in range(1800):
            await lim.acquire()
        await lim.acquire()                          # the 1801st
        assert c.t - 1000.0 >= 1800.0 and lim.count_in(1800.0) <= 1800

    async def test_windows_slide(self):
        c = FakeClock()
        lim = _limiter(c, [(2, 10.0)])
        await lim.acquire()
        c.t += 6
        await lim.acquire()
        c.t += 5                                     # the first call has now aged out
        assert await lim.acquire() == 0.0
        assert await lim.acquire() == pytest.approx(5.001)   # 1006 ages out at 1016 (+1 ms guard)

    async def test_long_run_never_exceeds_any_window(self):
        c = FakeClock()
        lim = _limiter(c)
        rnd = random.Random(7)
        stamps = []
        for _ in range(10_000):
            await lim.acquire()
            stamps.append(c.t)
            c.t += rnd.choice([0.0, 0.0, 0.001, 0.02, 0.5])
        for limit, span in R.default_windows():
            j = 0
            for i, t in enumerate(stamps):
                while stamps[j] <= t - span:
                    j += 1
                assert i - j + 1 <= limit, (limit, span)

    async def test_concurrent_callers_never_overshoot(self):
        c = FakeClock()
        lim = _limiter(c, [(5, 1.0)])

        async def one():
            await lim.acquire()
            return c.t
        times = await asyncio.gather(*(one() for _ in range(23)))
        for t in times:
            assert sum(1 for u in times if t - 1.0 < u <= t) <= 5
        assert lim.admitted == 23

    async def test_a_call_exactly_span_old_still_counts(self):
        """The boundary case that float seconds got wrong: stay on the safe side."""
        c = FakeClock()
        lim = _limiter(c, [(1, 10.0)])
        await lim.acquire()
        c.t += 10.0
        assert await lim.acquire() == pytest.approx(0.001)

    def test_bad_windows_are_refused(self):
        with pytest.raises(ValueError):
            R.RateLimiter([(0, 1.0)])

    def test_shared_limiter_is_one_per_process(self):
        assert R.shared_limiter() is R.shared_limiter()


# ── client ──────────────────────────────────────────────────────────────────
def _client(handler, clock=None, **kw):
    clock = clock or FakeClock()
    transport = httpx.MockTransport(handler)
    return R.UpstoxRestClient(TOKEN, client=httpx.AsyncClient(transport=transport),
                              limiter=_limiter(clock), sleep=clock.sleep, **kw), clock


def _seq(*responses):
    """A handler that replays responses in order; an Exception is raised."""
    it = iter(responses)
    seen = []

    def handler(req):
        seen.append(req)
        r = next(it)
        if isinstance(r, Exception):
            raise r
        return r
    handler.seen = seen
    return handler


def _err(status, code, message="x"):
    return httpx.Response(status, json={"status": "error", "errors": [
        {"errorCode": code, "message": message}]})


class TestClient:
    async def test_200_bytes_are_returned_verbatim(self):
        body = b'{"status":"success","data":{"candles":[]}}'
        h = _seq(httpx.Response(200, content=body))
        c, _ = _client(h)
        r = await c.get("/v3/x")
        assert r.ok and r.data == body and r.error_codes == () and len(r.attempts) == 1
        assert h.seen[0].headers["authorization"] == f"Bearer {TOKEN}"
        assert TOKEN not in str(h.seen[0].url)

    async def test_vendor_4xx_is_returned_with_its_code_not_retried(self):
        h = _seq(_err(400, "UDAPI1148", "Invalid date range"))
        c, clock = _client(h)
        r = await c.get("/v3/x")
        assert (r.status, r.error_codes, len(r.attempts)) == (400, ("UDAPI1148",), 1)
        assert clock.slept == []

    @pytest.mark.parametrize("status", [401, 403])
    async def test_auth_failure_is_raised_once(self, status):
        h = _seq(_err(status, "UDAPI100050"))
        c, _ = _client(h)
        with pytest.raises(VendorAuthError) as e:
            await c.get("/v3/x")
        assert len(h.seen) == 1 and TOKEN not in str(e.value)

    async def test_429_stops_immediately(self):
        h = _seq(httpx.Response(429, text="Too Many Requests"))
        c, clock = _client(h)
        with pytest.raises(RateLimited):
            await c.get("/v3/x")
        assert len(h.seen) == 1 and clock.slept == []

    async def test_a_rate_limit_message_in_a_4xx_body_also_stops(self):
        h = _seq(_err(400, "UDAPI_UNKNOWN", "Rate limit exceeded for this API"))
        c, _ = _client(h)
        with pytest.raises(RateLimited):
            await c.get("/v3/x")
        assert len(h.seen) == 1

    async def test_transient_5xx_is_retried_with_backoff(self):
        ok = httpx.Response(200, content=b"{}")
        h = _seq(httpx.Response(503), httpx.Response(502), ok)
        c, clock = _client(h)
        r = await c.get("/v3/x")
        assert r.ok and [a.status for a in r.attempts] == [503, 502, 200]
        assert clock.slept == [1.0, 2.0]
        assert [a.backoff_wait_s for a in r.attempts] == [0.0, 1.0, 2.0]

    async def test_timeouts_exhaust_into_vendor_error(self):
        h = _seq(*[httpx.ReadTimeout("slow")] * 5)
        c, clock = _client(h)
        with pytest.raises(VendorError) as e:
            await c.get("/v3/x")
        assert len(h.seen) == 5 and clock.slept == [1.0, 2.0, 4.0, 8.0]
        assert "ReadTimeout" in str(e.value) and TOKEN not in str(e.value)

    async def test_connection_error_then_success(self):
        h = _seq(httpx.ConnectError("reset"), httpx.Response(200, content=b"{}"))
        c, _ = _client(h)
        r = await c.get("/v3/x")
        assert r.ok and [a.error for a in r.attempts] == ["ConnectError", None]

    async def test_every_attempt_passes_through_the_limiter(self):
        clock = FakeClock()
        h = _seq(httpx.Response(503), httpx.Response(200, content=b"{}"))
        c = R.UpstoxRestClient(TOKEN, client=httpx.AsyncClient(transport=httpx.MockTransport(h)),
                               limiter=_limiter(clock, [(1, 10.0)]), sleep=clock.sleep)
        r = await c.get("/v3/x")
        assert c.limiter.admitted == 2
        assert r.attempts[1].limiter_wait_s == pytest.approx(9.001)   # 10 s - 1 s backoff + guard

    async def test_jitter_is_added_to_backoff(self):
        h = _seq(httpx.Response(500), httpx.Response(200, content=b"{}"))
        c, clock = _client(h, jitter=lambda: 0.25)
        await c.get("/v3/x")
        assert clock.slept == [1.25]

    def test_no_token_is_refused(self):
        with pytest.raises(VendorAuthError):
            R.UpstoxRestClient("")

    async def test_relative_path_is_refused(self):
        c, _ = _client(_seq())
        with pytest.raises(ValueError):
            await c.get("v3/x")

    def test_error_codes_parser(self):
        assert R.error_codes(json.dumps({"errors": [{"errorCode": "A"}, {"error_code": "B"}]})
                             .encode()) == ("A", "B")
        assert R.error_codes(b"<html>") == () and R.error_codes(b'{"errors": "x"}') == ()


# ── paths ───────────────────────────────────────────────────────────────────
class TestPaths:
    K = "NSE_EQ|INE002A01018"

    def test_historical_path_matches_the_measured_form(self):
        p = R.historical_candle_path(self.K, "1m", Window(D(2026, 8, 1), D(2026, 8, 31)))
        assert p == "/v3/historical-candle/NSE_EQ%7CINE002A01018/minutes/1/2026-08-31/2026-08-01"

    @pytest.mark.parametrize("tf, unit_step", [
        ("1m", "minutes/1"), ("5m", "minutes/5"), ("15m", "minutes/15"), ("1h", "hours/1"),
        ("1d", "days/1")])
    def test_every_m4_timeframe_maps_to_the_measured_unit(self, tf, unit_step):
        assert tf in M4_TIMEFRAMES
        assert f"/{unit_step}" in R.intraday_candle_path(self.K, tf)
        w = plan_windows(tf, D(2026, 8, 1), D(2026, 8, 31)).windows[0]
        assert f"/{unit_step}/" in R.historical_candle_path(self.K, tf, w)

    def test_a_window_over_the_span_limit_is_refused(self):
        with pytest.raises(ValueError):
            R.historical_candle_path(self.K, "1m", Window(D(2026, 7, 1), D(2026, 8, 31)))

    def test_a_window_before_availability_is_refused(self):
        with pytest.raises(ValueError):
            R.historical_candle_path(self.K, "1m", Window(D(2021, 12, 1), D(2021, 12, 31)))

    def test_index_keys_are_encoded(self):
        assert "NSE_INDEX%7CNifty%2050" in R.intraday_candle_path("NSE_INDEX|Nifty 50", "1m")

    def test_quotes_take_at_most_500_keys(self):
        assert R.quotes_path([self.K]).endswith("NSE_EQ%7CINE002A01018")
        R.quotes_path([f"NSE_EQ|K{i}" for i in range(500)])
        with pytest.raises(ValueError):
            R.quotes_path([f"NSE_EQ|K{i}" for i in range(501)])
        with pytest.raises(ValueError):
            R.quotes_path([])


# ── calendar client now rides on the shared client ─────────────────────────
class TestCalendarClient:
    def _cal(self, handler):
        clock = FakeClock()
        rest = R.UpstoxRestClient(TOKEN, client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler)), limiter=_limiter(clock), sleep=clock.sleep)
        return UpstoxCalendarClient(TOKEN, rest=rest)

    async def test_holidays_success(self):
        body = b'{"status":"success","data":[]}'
        f = await self._cal(_seq(httpx.Response(200, content=body))).holidays()
        assert f.data == body and f.http_status == 200 and f.url.endswith("/v2/market/holidays")

    async def test_expired_token_is_auth_error(self):
        with pytest.raises(VendorAuthError):
            await self._cal(_seq(_err(401, "UDAPI100050"))).timings(D(2026, 9, 24))

    async def test_transient_error_is_retried(self):
        ok = httpx.Response(200, content=b'{"status":"success","data":[]}')
        h = _seq(httpx.Response(503), ok)
        f = await self._cal(h).timings(D(2026, 9, 24))
        assert f.http_status == 200 and len(h.seen) == 2

    async def test_other_4xx_is_still_an_error_for_the_calendar(self):
        with pytest.raises(VendorError):
            await self._cal(_seq(_err(400, "UDAPI1015"))).timings(D(2026, 9, 24))
