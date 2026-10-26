"""app/shadow/store.py on the test database: freeze, token, forward-start refusal,
idempotency, never-overwrite, SHADOW-only and append-only rules."""

from __future__ import annotations

import datetime as _dt
import os

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.errors import AuthorizationError
from app.shadow import job as J
from app.shadow import spec as SP
from app.shadow import store as SS
from app.shadow.bars import at

pytestmark = [pytest.mark.db, pytest.mark.integration]
TOKEN = os.environ["PRAJNA_WRITE_TOKEN"]
FWD = _dt.date(2026, 11, 2)
DAY = _dt.date(2026, 11, 3)


@pytest.fixture
def forward(monkeypatch):
    monkeypatch.setattr(SP, "FORWARD_FROM", FWD)


def _out(net=-1234.5):
    t = at(DAY, "10:00")
    trade = {"strategy": "vwap_revert_core_v1", "instrument_key": "NSE_EQ|INE000000001", "side": 1,
             "is_placebo": False, "signal_at": t, "entry_at": t,
             "exit_at": t + _dt.timedelta(minutes=60), "time_stop": t + _dt.timedelta(minutes=60),
             "entry_raw": 100.0, "stop": 98.0, "target": 103.0, "atr": 2.0, "qty": 500,
             "size_factor": 1.0, "risk_inr": 1000.0, "rrr": 1.5,
             "checklist": {"p1_pattern": True}, "checklist_score": 5, "exit_raw": 98.0,
             "exit_reason": "STOP", "entry_px": 100.05, "exit_px": 97.95, "gross_inr": -1050.0,
             "charges": {"brokerage": 47.2}, "net_inr": net, "net_r": net / 1000.0,
             "by_slippage": {"0": {"net_inr": net}}, "sector": "IT", "regime_state": "RANGE",
             "risk_mult": 0.5, "day_type": "RANGE_DAY", "guard_flags": [], "evidence": {}}
    return {"snapshots": [{"checkpoint": "PRE", "features": {"a": 1}, "state": "RANGE",
                           "rule_fired": "5:adx<20", "risk_mult": 0.5, "day_type": None}],
            "trades": [trade],
            "skips": [{"strategy": SP.S1, "instrument_key": "NSE_EQ|INE000000002",
                       "reason": "SKIP_RRR", "signal_at": t, "detail": {"rrr": 0.9}}],
            "counts": {"universe": 1}, "state": "RANGE"}


INP = {"inputs_sha256": "a" * 64}


async def _n(s, t):
    return (await s.execute(text(f"select count(*) from {t}"))).scalar()


async def test_record_refused_before_the_freeze(db_session, forward):
    with pytest.raises(J.ShadowRefused, match="not frozen"):
        await SS.record(db_session, DAY, INP, _out(), cutoff=at(DAY, "21:30"), token=TOKEN,
                        code_git_sha="abc")


async def test_freeze_needs_the_token_and_the_code_forward_date(db_session, forward):
    with pytest.raises(AuthorizationError):
        await SS.freeze(db_session, forward_from=FWD, token="wrong", code_git_sha="abc")
    with pytest.raises(J.ShadowRefused, match="FORWARD_FROM"):
        await SS.freeze(db_session, forward_from=DAY, token=TOKEN, code_git_sha="abc")
    r = await SS.freeze(db_session, forward_from=FWD, token=TOKEN, code_git_sha="abc")
    assert r["status"] == "WRITTEN" and r["spec_sha256"] == SP.spec_sha256()
    r = await SS.freeze(db_session, forward_from=FWD, token=TOKEN, code_git_sha="abc")
    assert r["status"] == "ALREADY_PRESENT"


async def test_record_once_never_overwrite_and_forward_only(db_session, forward):
    s = db_session
    await SS.freeze(s, forward_from=FWD, token=TOKEN, code_git_sha="abc")
    with pytest.raises(J.ShadowRefused, match="before the forward start"):
        await SS.record(s, _dt.date(2026, 10, 30), INP, _out(), cutoff=at(DAY, "21:30"),
                        token=TOKEN, code_git_sha="abc")
    with pytest.raises(AuthorizationError):
        await SS.record(s, DAY, INP, _out(), cutoff=at(DAY, "21:30"), token=None,
                        code_git_sha="abc")
    r = await SS.record(s, DAY, INP, _out(), cutoff=at(DAY, "21:30"), token=TOKEN,
                        code_git_sha="abc")
    assert r["status"] == "WRITTEN"
    assert [await _n(s, t) for t in ("shadow_run", "regime_snapshot", "shadow_trade",
                                     "shadow_skip")] == [1, 1, 1, 1]
    r = await SS.record(s, DAY, INP, _out(), cutoff=at(DAY, "22:30"), token=TOKEN,
                        code_git_sha="abc")
    assert r["status"] == "ALREADY_PRESENT" and await _n(s, "shadow_trade") == 1
    with pytest.raises(J.ShadowRefused, match="never overwritten"):
        await SS.record(s, DAY, INP, _out(net=-1.0), cutoff=at(DAY, "21:30"), token=TOKEN,
                        code_git_sha="abc")
    assert await SS.prior_daily_net(s, DAY + _dt.timedelta(days=1)) == {"vwap_revert_core_v1": [-1234.5]}


async def test_skipped_session_is_recorded(db_session, forward):
    s = db_session
    await SS.freeze(s, forward_from=FWD, token=TOKEN, code_git_sha="abc")
    r = await SS.record(s, DAY, {"skipped": "SPECIAL session"}, {}, cutoff=at(DAY, "21:30"),
                        token=TOKEN, code_git_sha="abc")
    assert r["status"] == "WRITTEN_SKIPPED"
    st = (await s.execute(text("select status, reason from shadow_run"))).first()
    assert tuple(st) == ("SKIPPED", "SPECIAL session")


async def test_append_only_and_shadow_only(db_session, forward):
    s = db_session
    await SS.freeze(s, forward_from=FWD, token=TOKEN, code_git_sha="abc")
    await SS.record(s, DAY, INP, _out(), cutoff=at(DAY, "21:30"), token=TOKEN,
                    code_git_sha="abc")
    for sql in ("update shadow_trade set qty = 1", "delete from shadow_skip",
                "update shadow_policy set forward_from = '2026-01-01'"):
        with pytest.raises(DBAPIError, match="append-only"):
            async with s.begin_nested():
                await s.execute(text(sql))
    rid = (await s.execute(text("select run_id from shadow_run"))).scalar()
    with pytest.raises(DBAPIError, match="ck_shadow_trade_shadow_only"):
        async with s.begin_nested():
            await s.execute(text("""insert into shadow_trade (run_id, policy_version,
                market_date, strategy, instrument_key, side, is_placebo, signal_at, entry_at,
                exit_at, time_stop, entry_raw, stop, target, atr, qty, size_factor, risk_inr,
                rrr, checklist, checklist_score, exit_raw, exit_reason, entry_px, exit_px,
                gross_inr, charges, net_inr, net_r, by_slippage, regime_state, risk_mult,
                guard_flags, evidence, mode) select run_id, policy_version, market_date,
                strategy, 'NSE_EQ|X', side, is_placebo, signal_at, entry_at, exit_at, time_stop,
                entry_raw, stop, target, atr, qty, size_factor, risk_inr, rrr, checklist,
                checklist_score, exit_raw, exit_reason, entry_px, exit_px, gross_inr, charges,
                net_inr, net_r, by_slippage, regime_state, risk_mult, guard_flags, evidence,
                'LIVE' from shadow_trade where run_id = :r"""), {"r": rid})
