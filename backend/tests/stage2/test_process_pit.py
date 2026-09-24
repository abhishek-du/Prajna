"""Stage 2 on a real (test) database: processing, idempotency, increments,
crash recovery, look-ahead prevention, quality gates, DB constraints."""

from __future__ import annotations

import datetime as _dt
import os

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.canon import pit
from app.canon import process as P
from app.canon.quality import run_gates
from app.core import clock
from app.core.clock import IST
from tests.support import stage2_seed as SEED
from tests.support.stage2_seed import FUT, NOW, REIT, SPX, H, N, R, ist

pytestmark = [pytest.mark.db, pytest.mark.integration]
TOKEN = os.environ["PRAJNA_WRITE_TOKEN"]
D = _dt.date


@pytest.fixture
async def world(db_session):
    clock.freeze(NOW)
    ids = await SEED.seed(db_session)
    yield db_session, ids
    clock.unfreeze()


async def _q(s, sql, **kw):
    return (await s.execute(text(sql), kw)).all()


async def _process(s, **kw):
    return await P.process(s, commit=True, token=TOKEN, **kw)


async def _states(s, key, tf="1d"):
    return [(r.from_date.day, r.to_date.day, r.state) for r in await _q(s, """
        select c.* from canon_coverage c join canon_instrument ci using (instrument_id)
        where ci.instrument_key = :k and c.timeframe = :tf order by from_date""", k=key, tf=tf)]


class TestProcessing:
    async def test_universe_decisions_and_enrichment(self, world):
        s, _ = world
        rep = await _process(s)
        assert rep.status == "COMPLETE" and rep.instruments["current"] == 6
        rows = {r.instrument_key: r for r in await _q(s, "select * from canon_instrument")}
        assert {k for k, r in rows.items() if r.included} == {R, H, N}
        for k in (REIT, SPX, FUT):
            assert not rows[k].included and rows[k].filter_reason
        assert rows[R].sector == "Refineries"          # the latest profile snapshot
        assert rows[R].sector_knowable_at == ist(2026, 9, 20, 12)
        assert rows[SPX].segment == "GLOBAL_INDEX"      # traceable, not dropped

    async def test_every_coverage_state_is_represented(self, world):
        s, _ = world
        await _process(s)
        assert await _states(s, R) == [(14, 18, "DATA"), (21, 21, "EMPTY"), (22, 22, "DATA"),
                                       (23, 23, "QUARANTINED")]
        assert await _states(s, H) == [(14, 23, "VENDOR_ERROR")]
        assert await _states(s, N) == [(14, 23, "MISSING")]
        assert await _states(s, R, "1h") == [(14, 23, "PENDING_BACKFILL")]
        assert await _q(s, "select 1 from canon_coverage c join canon_instrument ci "
                           "using (instrument_id) where ci.instrument_key = any(:k)",
                        k=[REIT, SPX, FUT]) == []      # excluded instruments: no coverage

    async def test_idempotent_three_runs(self, world):
        s, _ = world
        first = await _process(s)
        snap = await _q(s, "select * from canon_coverage order by 1, 2, 3")
        inst = await _q(s, "select instrument_id, content_sha256 from canon_instrument order by 1")
        for _ in range(2):
            again = await _process(s)
            assert again.mode == "NOOP" and again.instruments["inserted"] == 0
            assert again.instruments["updated"] == 0
            assert [tuple(r)[:8] for r in await _q(
                s, "select * from canon_coverage order by 1, 2, 3")] == \
                [tuple(r)[:8] for r in snap]
            assert await _q(s, "select instrument_id, content_sha256 from canon_instrument "
                               "order by 1") == inst
        assert first.mode == "FULL"

    async def test_incremental_update_touches_only_the_new_pair(self, world):
        s, ids = world
        await _process(s)
        # Stage 1 adds a COMPLETE HDFCBANK window with a bar on 09-23
        rid = await SEED._run(s, f"ohlcv.1d.{H}", params={
            "window": ["2026-09-14", "2026-09-23"], "endpoint": "historical"},
            finished=NOW + _dt.timedelta(minutes=1))
        sha = await SEED._payload(s, rid)
        await s.execute(text("""
            insert into ohlcv_bar (instrument_id, timeframe, session_date, bar_start_utc, source,
              instrument_key, open, high, low, close, volume, vendor_ts_raw, run_id,
              payload_sha256, fetched_at, knowable_at, knowable_at_basis)
            values (:i, '1d', '2026-09-23', :b, 'UPSTOX_REST_V3', :k, 10, 11, 9, 10, 5, 'x',
                    :r, :h, :f, :f, 't')"""),
            {"i": ids[H], "b": ist(2026, 9, 23), "k": H, "r": rid, "h": sha,
             "f": ist(2026, 9, 24, 8)})
        rep = await _process(s)
        assert rep.mode == "INCREMENTAL"
        assert rep.coverage["1d"]["pairs"] == 1 and rep.coverage["1d"]["pairs_changed"] == 1
        assert await _states(s, H) == [(14, 22, "EMPTY"), (23, 23, "DATA")]
        assert (await _states(s, R))[0] == (14, 18, "DATA")    # untouched

    async def test_crash_rolls_back_and_the_rerun_resumes(self, world, monkeypatch):
        s, _ = world
        real = P.build_coverage

        async def boom(*a, **kw):
            raise ConnectionResetError("database went away")
        monkeypatch.setattr(P, "build_coverage", boom)
        with pytest.raises(ConnectionResetError):
            await _process(s)
        assert await _q(s, "select * from canon_instrument") == []
        assert await _q(s, "select * from canon_coverage") == []
        st = await _q(s, "select status from ingest_run where stream = 'canon.process'")
        assert [x.status for x in st] == ["FAILED"]
        monkeypatch.setattr(P, "build_coverage", real)
        assert (await _process(s)).status == "COMPLETE"

    async def test_dry_run_writes_nothing(self, world):
        s, _ = world
        rep = await P.process(s, commit=False, token=None)
        assert rep.status == "COMPLETE"
        assert await _q(s, "select * from canon_instrument") == []
        assert await _q(s, "select * from canon_coverage") == []


class TestPointInTime:
    """Look-ahead is impossible through the Stage 3 read API."""

    async def test_daily_bar_invisible_before_it_was_knowable(self, world):
        s, _ = world
        await _process(s)
        assert await pit.bars(s, R, "1d", ist(2026, 9, 24, 8, 0)) == []       # boundary
        got = await pit.bars(s, R, "1d", ist(2026, 9, 24, 8, 0, 0, 1))
        assert len(got) == 6 and got[-1]["market_date"] == D(2026, 9, 22)
        assert got[0]["event_start"].astimezone(IST).time() == _dt.time(9, 15)
        assert all(r["knowable_at"] >= r["event_end"] for r in got)

    async def test_quarantined_bar_never_appears(self, world):
        s, _ = world
        await _process(s)
        got = await pit.bars(s, R, "1d", NOW + _dt.timedelta(days=30))
        assert D(2026, 9, 23) not in {r["market_date"] for r in got}

    async def test_corporate_action_announced_0924_is_invisible_on_0923(self, world):
        s, _ = world
        await _process(s)
        assert await pit.corporate_actions(s, ist(2026, 9, 23, 23, 0), R) == []
        assert await pit.corporate_actions(s, ist(2026, 9, 24, 23, 59, 59, 999000), R) == []
        assert len(await pit.corporate_actions(s, ist(2026, 9, 25, 0, 0), R)) == 1

    async def test_news_needs_both_publication_and_the_vendor_link(self, world):
        s, _ = world
        await _process(s)
        assert await pit.news(s, ist(2026, 9, 22, 12), R) == []      # published, not linked
        (n,) = await pit.news(s, ist(2026, 9, 24, 12), R)
        assert n["published_at"] == ist(2026, 9, 22, 10)

    async def test_fundamentals_as_of_picks_the_latest_knowable(self, world):
        s, _ = world
        await _process(s)
        assert await pit.sector(s, R, ist(2026, 9, 9)) is None
        assert await pit.sector(s, R, ist(2026, 9, 15)) == "Old"
        assert await pit.sector(s, R, ist(2026, 9, 21)) == "Refineries"

    async def test_preopen_does_not_leak_into_the_prior_session(self, world):
        s, _ = world
        await _process(s)
        assert await pit.preopen(s, R, ist(2026, 9, 22, 16)) == []
        assert await pit.preopen(s, R, ist(2026, 9, 23, 9, 5)) == []          # boundary
        (t,) = await pit.preopen(s, R, ist(2026, 9, 23, 9, 6))
        assert t["market_date"] == D(2026, 9, 23) and float(t["iep"]) == 1250.5

    async def test_non_nse_and_out_of_scope_are_refused(self, world):
        s, _ = world
        await _process(s)
        assert await pit.bars(s, SPX, "1d", NOW) == []            # not in the NSE universe
        with pytest.raises(pit.OutOfScope):
            await pit.bars(s, R, "5m", NOW)
        assert (await pit.coverage(s, R, "5m"))[0]["state"] == "OUT_OF_SCOPE"

    async def test_context_is_point_in_time_throughout(self, world):
        s, _ = world
        await _process(s)
        ctx = await pit.context(s, R, ist(2026, 9, 21))
        assert ctx["sector"] == "Refineries" and ctx["corporate_actions"] == []
        assert ctx["news"] == [] and ctx["daily_bars"] == []


class TestNonSessionBars:
    async def test_placeholder_bar_on_a_weekend_is_excluded_and_traced(self, world):
        """Real case (2025-04-26): flat, zero-volume vendor bars on a Saturday."""
        s, ids = world
        rid = await SEED._run(s, "ohlcv.1d.x")
        sha = await SEED._payload(s, rid)
        await s.execute(text("""
            insert into ohlcv_bar (instrument_id, timeframe, session_date, bar_start_utc, source,
              instrument_key, open, high, low, close, volume, vendor_ts_raw, run_id,
              payload_sha256, fetched_at, knowable_at, knowable_at_basis)
            values (:i, '1d', '2026-09-19', :b, 'UPSTOX_REST_V3', :k, 5, 5, 5, 5, 0, 'x', :r, :h,
                    :f, :f, 't')"""),
            {"i": ids[R], "b": ist(2026, 9, 19), "k": R, "r": rid, "h": sha,
             "f": ist(2026, 9, 24, 8)})
        await _process(s)
        got = await pit.bars(s, R, "1d", NOW + _dt.timedelta(days=30))
        assert D(2026, 9, 19) not in {r["market_date"] for r in got}
        (x,) = await _q(s, "select * from canon_excluded_bar")
        assert x.session_date == D(2026, 9, 19) and "WEEKEND" in x.reason
        rep = await run_gates(s)
        assert {g["gate"]: g["status"] for g in rep["gates"]}["non_session_bars_exposed"] == "PASS"
        assert rep["informational"]["bars_excluded_non_session (canon_excluded_bar)"] == 1


class TestQualityAndConstraints:
    async def test_gates_flag_the_seeded_inconsistency_only(self, world):
        s, _ = world
        await _process(s)
        rep = await run_gates(s)
        failed = {g["gate"] for g in rep["gates"] if g["status"] == "FAIL"}
        # the NIFTY MISSING range (on purpose) and the seed's short calendar
        assert failed == {"unexpected_gaps", "calendar_gaps_in_depth"}
        (g,) = [g for g in rep["gates"] if g["gate"] == "unexpected_gaps"]
        assert g["count"] == 1 and "checkpoint" in g["diagnostic"]

    async def test_orphan_instrument_gate(self, world):
        s, ids = world
        await _process(s)
        await s.execute(text("delete from canon_coverage where instrument_id = :i"),
                        {"i": ids[R]})
        await s.execute(text("delete from canon_instrument where instrument_id = :i"),
                        {"i": ids[R]})
        rep = await run_gates(s)
        assert {g["gate"]: g["status"] for g in rep["gates"]}["orphan_instruments"] == "FAIL"

    @pytest.mark.parametrize("sql", [
        "update canon_instrument set included = true where instrument_key = 'GLOBAL_INDEX|^GSPC'",
        "update canon_instrument set sector = 'X', sector_knowable_at = null "
        "where instrument_key = 'NSE_EQ|INE002A01018'",
        "update canon_coverage set state = 'DATA', bars = 0 where state = 'EMPTY'",
        "update canon_coverage set state = 'NOPE'",
        "update canon_coverage set timeframe = '5m'",
    ])
    async def test_db_constraints(self, world, sql):
        s, _ = world
        await _process(s)
        with pytest.raises(IntegrityError):
            async with s.begin_nested():
                await s.execute(text(sql))
