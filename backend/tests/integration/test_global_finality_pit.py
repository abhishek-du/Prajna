"""F-GLOBAL-FINALITY (2026-09-29): global-label finality must be evaluated AS OF the
snapshot, not now. Measured in production: DJI's 2026-09-25 label, confirmed before
the 2026-09-29 08:59:59 snapshot, was revised by the vendor at 12:40 that day; the
current view then withheld it and a recompute of the stored snapshot differed.
pit.global_bars(key, as_of) now applies the finality rules with only the
observations fetched before as_of."""

from __future__ import annotations

import datetime as _dt

import pytest
from sqlalchemy import text

from app.canon import pit
from app.core.clock import IST
from tests.integration.test_global_finality import N225, _seed_global
from tests.support.stage2_seed import _payload, _run

pytestmark = [pytest.mark.db, pytest.mark.integration]
D = _dt.date


def ist(*a):
    return _dt.datetime(*a, tzinfo=IST)


async def _bar(s, iid, day, close, fetched, rid, sha, *, flat=False, v=100):
    await s.execute(text("""
        insert into ohlcv_bar (instrument_id, timeframe, session_date, bar_start_utc, source,
          instrument_key, open, high, low, close, volume, vendor_ts_raw, run_id,
          payload_sha256, fetched_at, knowable_at, knowable_at_verified, knowable_at_basis)
        values (:i, '1d', :d, :b, 'UPSTOX_REST_V3', :k, :o, :h, :l, :c, :v, 'x', :r, :sha,
                :f, :f, false, 'fetched')"""),
        {"i": iid, "d": day, "b": ist(day.year, day.month, day.day), "k": N225,
         "o": close if flat else close - 1, "h": close if flat else close + 1,
         "l": close if flat else close - 1, "c": close, "v": v,
         "r": rid, "sha": sha, "f": fetched})


async def _obs(s, iid, day, close, fetched, klass, rid, sha):
    await s.execute(text("""
        insert into ohlcv_observation (instrument_id, timeframe, session_date, bar_start_utc,
          source, instrument_key, open, high, low, close, volume, run_id, payload_sha256,
          fetched_at, classification, reason, method_version)
        values (:i, '1d', :d, :b, 'UPSTOX_REST_V3', :k, :c, :c, :c, :c, 100, :r, :sha, :f,
                :cl, 'test', 'revision-v1')"""),
        {"i": iid, "d": day, "b": ist(day.year, day.month, day.day), "k": N225, "c": close,
         "r": rid, "sha": sha, "f": fetched, "cl": klass})


@pytest.fixture
async def world(db_session):
    s = db_session
    await _seed_global(s)
    iid = (await s.execute(text("select instrument_id from instrument where instrument_key=:k"),
                           {"k": N225})).scalar()
    rid = await _run(s, "ohlcv.1d." + N225, source="UPSTOX_REST_V3")
    sha = await _payload(s, rid, "UPSTOX_REST_V3")
    # label 09-24 first fetched 09-25 13:00; unchanged 21:10 (>= 6 h: CONFIRMED then);
    # REVISED by the vendor at 09-27 12:40
    await _bar(s, iid, D(2026, 9, 24), 1000.0, ist(2026, 9, 25, 13, 0), rid, sha)
    await _obs(s, iid, D(2026, 9, 24), 1000.0, ist(2026, 9, 25, 21, 10), "REOBSERVED", rid, sha)
    await _obs(s, iid, D(2026, 9, 24), 990.0, ist(2026, 9, 27, 12, 40), "GLOBAL_REVISION",
               rid, sha)
    # label 09-23: confirmed by age (first fetched >= 4 days after the label)
    await _bar(s, iid, D(2026, 9, 23), 980.0, ist(2026, 9, 27, 13, 0), rid, sha)
    # label 09-22: a placeholder (flat = previous close 09-21, no volume)
    await _bar(s, iid, D(2026, 9, 21), 970.0, ist(2026, 9, 25, 13, 0), rid, sha)
    await _bar(s, iid, D(2026, 9, 22), 970.0, ist(2026, 9, 26, 13, 0), rid, sha, flat=True, v=0)
    await s.commit()
    return s


async def _labels(s, at):
    return {r["label_date"]: (r["finality"], r["knowable_at"])
            for r in await pit.global_bars(s, N225, at)}


async def test_a_label_revised_after_as_of_is_still_final_at_as_of(world):
    before_confirmation = await _labels(world, ist(2026, 9, 25, 21, 0))
    assert D(2026, 9, 24) not in before_confirmation                 # not final yet
    between = await _labels(world, ist(2026, 9, 26, 9, 0))
    assert between[D(2026, 9, 24)] == ("CONFIRMED", ist(2026, 9, 25, 21, 10))  # the fix
    after = await _labels(world, ist(2026, 9, 28, 9, 0))
    assert D(2026, 9, 24) not in after                               # revised before as_of


async def test_now_equals_the_current_view_and_the_view_is_unchanged(world):
    now = ist(2026, 9, 30, 12, 0)
    view = {r[0]: (r[1], r[2]) for r in (await world.execute(text(
        """select label_date, finality, knowable_at from canon_global_bar
           where instrument_key = :k and knowable_at < :n"""), {"k": N225, "n": now})).all()}
    assert await _labels(world, now) == view
    assert D(2026, 9, 24) not in view                                # current: revised


async def test_age_confirmation_placeholder_and_knowable_boundary(world):
    at = ist(2026, 9, 28, 9, 0)
    got = await _labels(world, at)
    assert got[D(2026, 9, 23)] == ("CONFIRMED_BY_AGE", ist(2026, 9, 27, 13, 0))
    assert D(2026, 9, 22) not in got                                 # placeholder withheld
    assert D(2026, 9, 21) in got                                     # by age (4 d later)
    # strict knowable_at < as_of: at exactly the first fetch of 09-23 it is not visible
    assert D(2026, 9, 23) not in await _labels(world, ist(2026, 9, 27, 13, 0))
    for r in await pit.global_bars(world, N225, at):
        assert r["knowable_at"] < at
