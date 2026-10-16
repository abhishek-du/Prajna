"""The paper job on the test database: strategy -> risk -> simulate -> record, in session
order, the risk state from earlier paper days, the halt, and the Stage 8 report."""

from __future__ import annotations

import datetime as _dt
import os

import pytest
from sqlalchemy import text

from app.canon import process as P
from app.core import clock
from app.core.clock import IST
from app.paper import job as J
from app.paper import monitor as MO
from app.paper import risk as RK
from app.paper import strategies as ST
from app.paper.targets import Target, TargetList
from tests.support import stage2_seed as SEED
from tests.support.stage2_seed import NOW, H, R

pytestmark = [pytest.mark.db, pytest.mark.integration]
TOKEN = os.environ["PRAJNA_WRITE_TOKEN"]
DAYS = [_dt.date(2026, 9, d) for d in (15, 16, 17, 18)]     # RELIANCE has 1d bars


@pytest.fixture
async def world(db_session, monkeypatch):
    clock.freeze(NOW)
    await SEED.seed(db_session)
    await P.process(db_session, commit=True, token=TOKEN)

    def fixed(m, d):
        return TargetList("fixed", d, _dt.datetime.combine(d, _dt.time(9, 0), tzinfo=IST),
                          (Target(R, 1, 1.0), Target(H, 2, 0.5)), "test").validate()
    monkeypatch.setitem(ST.STRATEGIES, "fixed", fixed)
    ctx = {R: {"sector": "ENERGY", "prev_close": 105.0, "turnover": 1e9},
           H: {"sector": "BANK", "prev_close": 105.0, "turnover": 1e3}}   # H: illiquid
    monkeypatch.setattr(ST, "context", lambda m, d: ctx)
    yield db_session, ST.Market(DAYS, {}, {})
    clock.unfreeze()


async def test_replay_records_targets_risk_and_fills_in_order(world):
    s, m = world
    out = await J.replay(s, m, "fixed", DAYS[0], DAYS[-1], commit=True, token=TOKEN)
    assert [r["status"] for r in out] == ["WRITTEN"] * 4
    assert all(r["rejected"] == 1 and r["targets"] == 1 for r in out)    # H: min_turnover
    dec = (await s.execute(text("""select instrument_key, decision, reason
        from paper_risk_decision order by id limit 2"""))).all()
    assert [tuple(d) for d in dec] == [(R, "APPROVED", None), (H, "REJECTED", "min_turnover")]
    tl = (await s.execute(text("select target_list from paper_run limit 1"))).scalar()
    assert TargetList.from_dict(tl).keys == [R, H]                  # the full list is kept
    again = await J.replay(s, m, "fixed", DAYS[0], DAYS[-1], commit=True, token=TOKEN)
    assert {r["status"] for r in again} == {"ALREADY_PRESENT"}


async def test_daily_loss_halts_the_next_day_only(world):
    s, m = world
    from app.paper import sim
    lossy = sim.Config(slippage_bps=600.0)            # 100 -> 105 becomes a sure loss
    out = await J.replay(s, m, "fixed", DAYS[0], DAYS[-1], commit=True, token=TOKEN,
                         cfg=lossy, limits=RK.Limits(daily_loss_halt=1e-6))
    assert [r["targets"] for r in out] == [1, 0, 1, 0]          # a halted day loses nothing
    assert out[0]["pnl_inr"] < 0 and all(r["status"] == "WRITTEN" for r in out)
    reasons = (await s.execute(text("""select distinct reason from paper_risk_decision d
        join paper_run r using (run_id) where r.session_date = :d"""), {"d": DAYS[1]})).scalars()
    assert set(reasons) == {"halted_daily_loss"}


async def test_drawdown_halts_until_reviewed(world):
    s, m = world
    from app.paper import sim
    out = await J.replay(s, m, "fixed", DAYS[0], DAYS[-1], commit=True, token=TOKEN,
                         cfg=sim.Config(slippage_bps=600.0),
                         limits=RK.Limits(max_drawdown_halt=1e-6))
    assert [r["targets"] for r in out] == [1, 0, 0, 0]
    st = await J.state(s, "fixed", DAYS[-1], 1e6)
    assert st.drawdown_inr == pytest.approx(-out[0]["pnl_inr"], abs=1e-3)


async def test_report_reads_the_recorded_days(world):
    s, m = world
    await J.replay(s, m, "fixed", DAYS[0], DAYS[-1], commit=True, token=TOKEN)
    rows = await MO.daily(s, "fixed", DAYS[0], DAYS[-1])
    summ = MO.summary(rows)
    assert summ["recorded"] == 4 and summ["missing"] == []
    assert summ["total_return"] == pytest.approx(sum(r["ret"] for r in rows))
    assert await MO.scores(s, "fixed", DAYS[0], DAYS[-1]) == [1.0, 0.5] * 4


async def test_unknown_strategy_is_refused(world):
    s, m = world
    from app.paper.store import PaperRefused
    with pytest.raises(PaperRefused, match="unknown strategy"):
        await J.run_session(s, m, "nope", DAYS[0])


async def test_pending_starts_after_the_last_recorded_day_and_needs_stored_bars(world):
    s, m = world
    floor = DAYS[0]
    assert await J.pending(s, "fixed", floor) is None                 # no Nifty bar seeded
    from tests.support.stage2_seed import N
    rid = await SEED._run(s, "ohlcv.1d.x")
    sha = await SEED._payload(s, rid)
    ids = dict((await s.execute(text("select instrument_key, instrument_id from instrument"
                                     ))).all())
    await s.execute(text("""
        insert into ohlcv_bar (instrument_id, timeframe, session_date, bar_start_utc, source,
          instrument_key, open, high, low, close, volume, vendor_ts_raw, run_id,
          payload_sha256, fetched_at, knowable_at, knowable_at_basis)
        values (:i, '1d', '2026-09-18', :b, 'UPSTOX_REST_V3', :k, 10, 11, 9, 10, 0, 'x', :r,
                :h, :f, :f, 't')"""),
        {"i": ids[N], "b": _dt.datetime(2026, 9, 18, tzinfo=IST), "k": N, "r": rid,
         "h": sha, "f": _dt.datetime(2026, 9, 19, 8, tzinfo=IST)})
    await P.process(s, commit=True, token=TOKEN)
    assert await J.pending(s, "fixed", floor) == (DAYS[0], DAYS[-1])
    await J.replay(s, m, "fixed", DAYS[0], DAYS[1], commit=True, token=TOKEN)
    assert await J.pending(s, "fixed", floor) == (DAYS[2], DAYS[-1])
    await J.replay(s, m, "fixed", DAYS[2], DAYS[-1], commit=True, token=TOKEN)
    assert await J.pending(s, "fixed", floor) is None
