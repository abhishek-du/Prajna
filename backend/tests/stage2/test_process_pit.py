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
        """Announced 09-24 (KN-CA: end of that day), stored by Prajna 09-25 10:00.
        CA-OBSERVED (2026-10-09): knowable only once observed - KN-CA made it visible
        from 09-25 00:00, ten hours before Prajna had it."""
        s, _ = world
        await _process(s)
        assert await pit.corporate_actions(s, ist(2026, 9, 23, 23, 0), R) == []
        assert await pit.corporate_actions(s, ist(2026, 9, 24, 23, 59, 59, 999000), R) == []
        assert await pit.corporate_actions(s, ist(2026, 9, 25, 0, 0), R) == []
        assert await pit.corporate_actions(s, ist(2026, 9, 25, 10, 0), R) == []
        assert len(await pit.corporate_actions(s, ist(2026, 9, 25, 10, 0, 0, 1), R)) == 1

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
        assert (await pit.coverage(s, R, "5m", NOW))[0]["state"] == "OUT_OF_SCOPE"
        assert (await pit.current_coverage(s, R, "5m"))[0]["state"] == "OUT_OF_SCOPE"
        assert await pit.coverage(s, SPX, "1d", NOW) == []     # excluded: no coverage

    async def test_context_is_point_in_time_throughout(self, world):
        s, _ = world
        await _process(s)
        ctx = await pit.context(s, R, ist(2026, 9, 21))
        assert ctx["sector"] == "Refineries" and ctx["corporate_actions"] == []
        assert ctx["news"] == [] and ctx["daily_bars"] == []


def _cov(rows):
    return [(r["from_date"].day, r["to_date"].day, r["state"], r["bars"]) for r in rows]


class TestPointInTimeCoverage:
    """coverage(as_of) shows only what Stage 1 knew strictly before as_of. The
    seed's runs finish 09-24 11:00 IST; RELIANCE's bars are knowable 08:00."""

    async def test_historical_as_of_cannot_see_future_sessions_or_ingestion(self, world):
        s, _ = world
        await _process(s)
        # 09-17: RELIANCE traded 14..22 and a later window ran, but none of it
        # was known yet: only the past sessions, all PENDING_BACKFILL, no bars
        early = ist(2026, 9, 17, 12)
        assert _cov(await pit.coverage(s, R, "1d", early)) == [(14, 16, "PENDING_BACKFILL", 0)]
        assert _cov(await pit.coverage(s, H, "1d", early)) == [(14, 16, "PENDING_BACKFILL", 0)]
        assert _cov(await pit.coverage(s, N, "1d", early)) == [(14, 16, "PENDING_BACKFILL", 0)]
        assert await pit.bars(s, R, "1d", early) == []

    async def test_bars_become_data_exactly_when_bars_does(self, world):
        s, _ = world
        await _process(s)
        at = ist(2026, 9, 24, 8, 0)                       # bars knowable AT 08:00: not yet
        assert {r["state"] for r in await pit.coverage(s, R, "1d", at)} == {
            "PENDING_BACKFILL"}
        # 1 us later the bars are visible; the windows, the quarantine and the
        # failure (runs finished 11:00) are not: 21 and 23 are still pending
        at = ist(2026, 9, 24, 8, 0, 0, 1)
        assert _cov(await pit.coverage(s, R, "1d", at)) == [
            (14, 18, "DATA", 5), (21, 21, "PENDING_BACKFILL", 0), (22, 22, "DATA", 1),
            (23, 23, "PENDING_BACKFILL", 0)]
        assert len(await pit.bars(s, R, "1d", at)) == 6
        assert _cov(await pit.coverage(s, H, "1d", at)) == [(14, 23, "PENDING_BACKFILL", 0)]
        # the run outcomes count only once their runs finished (strictly before)
        fin = ist(2026, 9, 24, 11, 0)
        assert _cov(await pit.coverage(s, H, "1d", fin)) == [(14, 23, "PENDING_BACKFILL", 0)]
        after = fin + _dt.timedelta(microseconds=1)
        assert _cov(await pit.coverage(s, R, "1d", after)) == [
            (14, 18, "DATA", 5), (21, 21, "EMPTY", 0), (22, 22, "DATA", 1),
            (23, 23, "QUARANTINED", 0)]
        assert _cov(await pit.coverage(s, H, "1d", after)) == [(14, 23, "VENDOR_ERROR", 0)]
        assert _cov(await pit.coverage(s, N, "1d", after)) == [(14, 23, "MISSING", 0)]

    async def test_a_later_ingest_changes_current_coverage_not_the_past(self, world):
        s, _ = world
        # HDFCBANK's failed window is retried successfully on 09-25 10:00
        await SEED._run(s, f"ohlcv.1d.{H}", started=ist(2026, 9, 25, 9),
                        finished=ist(2026, 9, 25, 10), params={
                            "window": ["2026-09-14", "2026-09-23"], "endpoint": "historical",
                            "instrument_key": H, "timeframe": "1d"})
        await _process(s)
        assert _cov(await pit.current_coverage(s, H, "1d")) == [(14, 23, "EMPTY", 0)]
        assert _cov(await pit.coverage(s, H, "1d", NOW)) == [(14, 23, "VENDOR_ERROR", 0)]
        # on 09-25 the 09-24 session is past (not yet ingested); the retry counts
        # only strictly after it finished
        assert _cov(await pit.coverage(s, H, "1d", ist(2026, 9, 25, 10))) == [
            (14, 23, "VENDOR_ERROR", 0), (24, 24, "PENDING_BACKFILL", 0)]
        assert _cov(await pit.coverage(s, H, "1d", ist(2026, 9, 25, 10, 0, 0, 1))) == [
            (14, 23, "EMPTY", 0), (24, 24, "PENDING_BACKFILL", 0)]

    async def test_current_coverage_is_the_materialized_state_for_live_use(self, world):
        s, _ = world
        await _process(s)
        cur = await pit.current_coverage(s, R, "1d")
        assert _cov(cur) == [(14, 18, "DATA", 5), (21, 21, "EMPTY", 0), (22, 22, "DATA", 1),
                             (23, 23, "QUARANTINED", 0)]
        assert all(r["run_id"] for r in cur)
        # as of now, the point-in-time rules reproduce the materialized table
        # for every instrument and timeframe
        for key in (R, H, N):
            for tf in ("1d", "1h", "15m", "1m"):
                pitc = await pit.coverage(s, key, tf, NOW)
                cols = ("from_date", "to_date", "state", "sessions", "bars", "quarantined")
                assert [tuple(r[c] for c in cols) for r in pitc] == \
                    [tuple(r[c] for c in cols) for r in await pit.current_coverage(s, key, tf)]

    async def test_coverage_never_reaches_the_as_of_market_date(self, world):
        s, _ = world
        await _process(s)
        for at in (ist(2026, 9, 22, 0, 0), ist(2026, 9, 22, 15, 0), ist(2026, 9, 23, 0, 0, 0, 1)):
            rows = await pit.coverage(s, R, "1d", at)
            assert rows and max(r["to_date"] for r in rows) < at.date()


class TestPointInTimeSector:
    async def test_historical_sector_comes_from_snapshots_not_canon_instrument(self, world):
        s, _ = world
        await _process(s)
        # canon_instrument holds TODAY's sector; the past must not see it
        (cur,) = await _q(s, "select sector from canon_instrument where instrument_key = :k",
                          k=R)
        assert cur.sector == "Refineries"
        assert await pit.sector(s, R, ist(2026, 9, 15)) == "Old"
        assert (await pit.context(s, R, ist(2026, 9, 15)))["sector"] == "Old"
        assert await pit.sector(s, R, ist(2026, 9, 9)) is None
        # pit never reads the current column: changing it changes nothing
        await s.execute(text("update canon_instrument set sector = 'TAMPERED' "
                             "where instrument_key = :k"), {"k": R})
        assert await pit.sector(s, R, ist(2026, 9, 15)) == "Old"
        assert await pit.sector(s, R, NOW) == "Refineries"         # live: latest knowable
        assert (await pit.context(s, R, NOW))["sector"] == "Refineries"

    async def test_sector_boundary_is_strict(self, world):
        s, _ = world
        await _process(s)
        assert await pit.sector(s, R, ist(2026, 9, 20, 12)) == "Old"          # AT: not yet
        assert await pit.sector(s, R, ist(2026, 9, 20, 12, 0, 0, 1)) == "Refineries"


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


class TestLifecycleCoverage:
    """Hardening phase 2: coverage of an instrument that left the master stops
    where it left (no endless PENDING_BACKFILL), its bars stay visible, and a
    historical as_of never learns of a removal that was not knowable yet."""

    async def _remove(self, s, key, at, known):
        iid = (await s.execute(text("select instrument_id from instrument where instrument_key=:k"),
                               {"k": key})).scalar()
        row = (await s.execute(text("select run_id, payload_sha256 from instrument where "
                                    "instrument_id=:i"), {"i": iid})).one()
        for status, frm, to in (("ACTIVE", ist(2026, 9, 1), at), ("REMOVED_FROM_MASTER", at, None)):
            await s.execute(text("""
                insert into instrument_lifecycle_period (instrument_id, status, valid_from,
                  valid_to, reason, source, run_id, payload_sha256, fetched_at, knowable_at,
                  knowable_at_verified, knowable_at_basis)
                values (:i, :st, :f, coalesce(cast(:t as timestamptz), 'infinity'), 'test',
                        'UPSTOX_ASSETS', :r, :h, :k, :k, false, 't')"""),
                {"i": iid, "st": status, "f": frm, "t": to, "r": row[0], "h": row[1],
                 "k": max(known, frm)})
        await s.execute(text("update instrument set lifecycle_status='REMOVED_FROM_MASTER' "
                             "where instrument_id=:i"), {"i": iid})

    async def test_removed_instrument_coverage_stops_and_bars_stay(self, world):
        s, _ = world
        # effective 09-18 07:00, but Prajna only learned it on 09-23 10:00
        await self._remove(s, R, ist(2026, 9, 18, 7, 0), known=ist(2026, 9, 23, 10, 0))
        await _process(s)
        (ci,) = await _q(s, "select lifecycle_status, lifecycle_since from canon_instrument "
                            "where instrument_key=:k", k=R)
        assert ci.lifecycle_status == "REMOVED_FROM_MASTER"
        assert await _states(s, R) == [(14, 17, "DATA")]        # sessions before 09-18 only
        assert await _states(s, R, "1h") == [(14, 17, "PENDING_BACKFILL")]
        got = await pit.bars(s, R, "1d", NOW)
        assert len(got) == 6                                     # history still visible
        # PIT: before the removal was knowable the historical view is not shortened
        after = await pit.coverage(s, R, "1d", ist(2026, 9, 24, 9, 0))      # known by then
        assert max(r["to_date"] for r in after) == D(2026, 9, 17)
        at_21 = await pit.coverage(s, R, "1d", ist(2026, 9, 21, 12, 0))
        assert (min(r["from_date"] for r in at_21), max(r["to_date"] for r in at_21)) == (
            D(2026, 9, 14), D(2026, 9, 18))                   # 09-18 still expected on 09-21
        later = await pit.coverage(s, R, "1d", NOW)
        assert max(r["to_date"] for r in later) == D(2026, 9, 17)
        assert [r["state"] for r in later] == ["DATA"]
