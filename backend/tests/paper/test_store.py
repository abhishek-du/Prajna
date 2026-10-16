"""app/paper/store.py on the test database: bars from the canonical layer, dry run,
token, idempotency, never-overwrite, and the database's PAPER-only and append-only rules."""

from __future__ import annotations

import datetime as _dt
import os

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.canon import process as P
from app.core import clock
from app.core.errors import AuthorizationError
from app.paper import store as ST
from tests.support import stage2_seed as SEED
from tests.support.stage2_seed import NOW, H, R

pytestmark = [pytest.mark.db, pytest.mark.integration]
TOKEN = os.environ["PRAJNA_WRITE_TOKEN"]
DAY = _dt.date(2026, 9, 18)            # RELIANCE 100/110/95/105, previous session volume 1000


@pytest.fixture
async def world(db_session):
    clock.freeze(NOW)
    await SEED.seed(db_session)
    await P.process(db_session, commit=True, token=TOKEN)
    yield db_session
    clock.unfreeze()


async def _n(s, table):
    return (await s.execute(text(f"select count(*) from {table}"))).scalar()


async def test_dry_run_reads_the_canonical_bars_and_writes_nothing(world):
    s = world
    out = await ST.simulate_session(s, "test", DAY, [R, H])
    assert out["status"] == "DRY_RUN" and out["mode"] == "PAPER" and out["bars_found"] == 1
    (r, h) = out["fills"]
    assert r["status"] == "PARTIAL" and r["qty"] == 10           # 1% of 1000 shares
    assert r["buy_px"] == pytest.approx(100 * 1.0005) and r["sell_px"] == pytest.approx(105 * 0.9995)
    assert h["status"] == "NOT_FILLED" and h["reason"] == "no_open_or_close"
    assert await _n(s, "paper_run") == 0


async def test_commit_needs_the_token(world):
    with pytest.raises(AuthorizationError):
        await ST.simulate_session(world, "test", DAY, [R], commit=True, token=None)
    with pytest.raises(AuthorizationError):
        await ST.simulate_session(world, "test", DAY, [R], commit=True, token="wrong")
    assert await _n(world, "paper_run") == 0


async def test_commit_records_the_day_once_and_never_overwrites(world):
    s = world
    out = await ST.simulate_session(s, "test", DAY, [R, H], commit=True, token=TOKEN,
                                    code_git_sha="abc")
    assert out["status"] == "WRITTEN"
    assert [await _n(s, t) for t in ("paper_run", "paper_order", "paper_fill", "paper_day")] \
        == [1, 2, 2, 1]
    day = (await s.execute(text("select * from paper_day"))).one()
    fills = (await s.execute(text("select * from paper_fill order by instrument_key"))).all()
    charges = sum(sum(float(v) for v in f.charges.values()) for f in fills)
    assert float(day.pnl_inr) == pytest.approx(
        sum(float(f.sell_value_inr - f.buy_value_inr) for f in fills) - charges, abs=1e-3)
    assert float(day.end_cash_inr - day.start_cash_inr) == pytest.approx(float(day.pnl_inr))
    assert {r.mode for r in fills} == {"PAPER"} and day.mode == "PAPER"

    again = await ST.simulate_session(s, "test", DAY, [R, H], commit=True, token=TOKEN)
    assert again["status"] == "ALREADY_PRESENT" and again["run_id"] == out["run_id"]
    with pytest.raises(ST.PaperRefused, match="never overwritten"):
        await ST.simulate_session(s, "test", DAY, [H, R], commit=True, token=TOKEN)
    assert await _n(s, "paper_run") == 1
    other = await ST.simulate_session(s, "other", DAY, [R], commit=True, token=TOKEN)
    assert other["status"] == "WRITTEN"                       # one run per strategy


async def test_invalid_input_is_refused(world):
    with pytest.raises(ST.PaperRefused, match="strategy name"):
        await ST.simulate_session(world, "bad name;", DAY, [R])
    with pytest.raises(ST.PaperRefused, match="no targets"):
        await ST.simulate_session(world, "test", DAY, [])
    with pytest.raises(ST.PaperRefused, match="no stored 1d bar"):
        await ST.simulate_session(world, "test", _dt.date(2026, 9, 24), [R])


async def test_the_database_admits_only_paper_rows_and_no_updates(world):
    s = world
    await ST.simulate_session(s, "test", DAY, [R], commit=True, token=TOKEN)
    rid = (await s.execute(text("select run_id from paper_run"))).scalar()
    for sql in ("update paper_fill set pnl_inr = 0", "delete from paper_day",
                f"""insert into paper_order (run_id, seq, instrument_key, product,
                    order_value_inr, mode) values ('{rid}', 9, 'X', 'MIS', 1, 'LIVE')""",
                f"""insert into paper_order (run_id, seq, instrument_key, product,
                    order_value_inr, mode) values ('{rid}', 9, 'X', 'CNC', 1, 'PAPER')"""):
        with pytest.raises(DBAPIError):
            async with s.begin_nested():
                await s.execute(text(sql))
