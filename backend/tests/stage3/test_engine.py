"""Stage 3 engine on a fully specified world (tests/support/stage3_seed.py):
values, corporate actions and price basis, point-in-time boundaries, look-ahead
probes, and the locked production path (idempotency, determinism, partial
failure, rollback, retry, crash and restart recovery, kill switch, every lock
condition). Test database only; no network."""

from __future__ import annotations

import datetime as _dt
import json
import os
import socket
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.canon import pit
from app.canon import process as P
from app.core import clock
from app.core.config import get_settings
from app.features import engine as E
from app.features import inputs as I
from app.features import locks
from app.features import snapshots as SN
from app.features.compute import ok
from app.features.decisions import DECISIONS
from app.ops.reaper import reap_runs
from tests.support import stage3_seed as W
from tests.support.stage2_seed import _payload, _run

pytestmark = [pytest.mark.db, pytest.mark.integration,
              pytest.mark.isolation("REPEATABLE READ")]   # run_snapshot needs one snapshot
TOKEN = os.environ["PRAJNA_WRITE_TOKEN"]
PRE_SESSION_AT = W.ist(2026, 9, 24, 8, 59, 59)
PRE_OPEN_AT = W.ist(2026, 9, 24, 9, 8)


@pytest.fixture
async def world(db_session):
    clock.freeze(W.NOW)
    ids = await W.seed(db_session)
    await P.process(db_session, commit=True, token=TOKEN)
    db_session.info["ids"] = ids
    yield db_session
    clock.unfreeze()


@pytest.fixture
def unlocked(monkeypatch, tmp_path):
    """Every lock condition satisfied (each test then breaks one on purpose)."""
    st = get_settings()
    monkeypatch.setattr(st, "PRAJNA_STAGE3_ENABLED", True)
    monkeypatch.setattr(st, "PRAJNA_STAGE3_BACKFILL_ENABLED", False)
    monkeypatch.setitem(DECISIONS["FEATURE-PARAMS"], "status", "APPROVED")
    monkeypatch.setattr(locks, "KILL_FILE", tmp_path / "stage3.kill")

    async def s1(_s):
        return True, "COMPLETE (test)"
    monkeypatch.setattr(locks, "stage1_status", s1)
    monkeypatch.setattr(locks, "stage2_status", lambda *a, **k: (True, "PASS (test)"))
    return st


async def snap(s, kind="PRE_SESSION", day=W.SESSION):
    return await SN.resolve(s, day, kind)


def by(res, key=None):
    return {(r.instrument_key, r.feature_id): (r.value, r.reason) for r in res.rows
            if key is None or r.instrument_key == key}


async def count(s, sql, **kw):
    return (await s.execute(text(sql), kw)).scalar()


# ── snapshots ────────────────────────────────────────────────────────────────
class TestSnapshots:
    async def test_normal_session_instants(self, world):
        a = await snap(world)
        b = await snap(world, "PRE_OPEN")
        assert a.as_of == PRE_SESSION_AT and b.as_of == PRE_OPEN_AT
        assert a.previous_session == _dt.date(2026, 9, 23)

    async def test_special_session_and_holiday(self, world):
        sp = await snap(world, "PRE_SESSION", W.SPECIAL)
        assert sp.as_of == W.ist(2026, 9, 19, 9, 14, 59)             # open - 1 s
        assert sp.previous_session == _dt.date(2026, 9, 18)
        with pytest.raises(SN.NoSnapshot):
            await snap(world, "PRE_OPEN", W.SPECIAL)                   # no pre-open window
        with pytest.raises(SN.NoSnapshot):
            await snap(world, "PRE_SESSION", _dt.date(2026, 9, 20))    # Sunday
        with pytest.raises(SN.NoSnapshot):
            await snap(world, "PRE_SESSION", _dt.date(2027, 1, 4))     # no calendar entry


# ── values ───────────────────────────────────────────────────────────────────
class TestValues:
    async def test_normal_path(self, world):
        res = await E.compute_snapshot(world, await snap(world), [W.A])
        v = by(res)
        n = len(W.history()) - 1                     # index of the last stored session
        assert v[(W.A, "ret_1d")] == (ok((100 + n) / (99 + n) - 1)[0], None)
        assert v[(W.A, "sma_20")] == (100 + n - 9.5, None)
        assert v[(W.A, "pe")] == (20.0, None) and v[(W.A, "pe_to_sector")] == (0.8, None)
        assert v[(W.A, "revenue_yoy")] == (0.2, None)
        assert v[(W.A, "liabilities_to_assets")] == (0.5, None)
        assert v[(W.A, "ca_days_to_dividend")] == (11.0, None)
        assert v[(W.A, "news_count_24h")] == (1.0, None)
        assert v[(W.A, "sma_200")] == (None, "INSUFFICIENT_HISTORY")
        assert v[("MARKET", "fii_net_cash_1d")] == (None, "MISSING_INPUT")
        assert v[(W.VIX, "india_vix_level")] == (ok(12 + 0.1 * n)[0], None)
        assert not any(k[1].startswith("preopen_") for k in v)       # PRE_OPEN only
        for r in res.rows:                                           # the reason contract
            assert (r.value is None) != (r.reason is None)
            assert r.input_max_knowable_at is None or r.input_max_knowable_at < res.snapshot.as_of

    async def test_preopen_only_at_pre_open(self, world):
        res = await E.compute_snapshot(world, await snap(world, "PRE_OPEN"), [W.A, W.B],
                                       with_context=False)
        v = by(res)
        n = len(W.history()) - 1
        assert v[(W.A, "preopen_gap_pct")] == (ok(180.5 / (100 + n) - 1)[0], None)
        assert v[(W.A, "preopen_imbalance")] == (0.5, None)
        assert v[(W.A, "preopen_ieq")] == (5000.0, None)
        assert v[(W.B, "preopen_gap_pct")] == (None, "MISSING_INPUT")   # no tick for B

    async def test_every_instrument_feature_is_emitted_once(self, world):
        res = await E.compute_snapshot(world, await snap(world, "PRE_OPEN"), list(W.STOCKS))
        keys = [(r.instrument_key, r.feature_id) for r in res.rows]
        assert len(keys) == len(set(keys))
        per = {k: sum(1 for r in res.rows if r.instrument_key == k) for k in W.STOCKS}
        assert len(set(per.values())) == 1                           # same feature set each

    async def test_partial_failure_malformed_payload_does_not_stop_the_run(self, world):
        res = await E.compute_snapshot(world, await snap(world), [W.DD, W.A])
        v = by(res)
        assert v[(W.DD, "pe")] == (None, "MALFORMED_INPUT")
        assert v[(W.DD, "ret_1d")][1] is None and v[(W.A, "pe")] == (20.0, None)


# ── corporate actions and price basis ────────────────────────────────────────
class TestPriceBasis:
    async def test_known_bonus_is_adjusted(self, world):
        """B trades at 2x A before its 1:1 bonus and 1x after: the adjusted series
        equals A's, so every price feature matches (volume features differ)."""
        res = await E.compute_snapshot(world, await snap(world), [W.A, W.B], with_context=False)
        v = by(res)
        for f in ("ret_1d", "ret_5d", "ret_20d", "sma_20", "sma_50", "ema_26", "rsi_14",
                  "macd_line", "volatility_20"):
            assert v[(W.B, f)] == v[(W.A, f)], f
        assert v[(W.B, "ca_days_since_bonus")] == (14.0, None)

    async def test_action_not_yet_knowable_is_not_applied(self, world):
        """A split of C (ex 09-15) that becomes knowable only AFTER the 09-24
        snapshots: at 09-24 C's bars are as stored; at 09-25 they are adjusted."""
        s, ids = world, world.info["ids"]
        rid = await _run(s, "facts.late", source="UPSTOX_REST_V2")
        sha = await _payload(s, rid, "UPSTOX_REST_V2")
        kn = W.ist(2026, 9, 24, 10, 0)
        ca = (await s.execute(text("""
            insert into corporate_action (isin, instrument_key, trading_symbol, action_type,
              ex_date, content_sha256, vendor_payload, source, run_id, payload_sha256,
              fetched_at, knowable_at, knowable_at_verified, knowable_at_basis)
            values ('INE000C00001', :k, 'CCC', 'SPLIT', '2026-09-15', :c, '{}',
                    'UPSTOX_REST_V2', :r, :h, :kn, :kn, false, 'KN-CA') returning id"""),
            {"k": W.C, "c": uuid.uuid4().hex * 2, "r": rid, "h": sha, "kn": kn})).scalar()
        await s.execute(text("""
            insert into ca_factor (ca_id, instrument_key, action_type, ex_date, status, method,
              factor_price, factor_volume, knowable_at, vendor_applied, reason, method_version,
              derived_at, run_id) values (:c, :k, 'SPLIT', '2026-09-15', 'EXACT', 'SPLIT_FV', 2,
              2, :kn, 'NOT_APPLIED', 'test', 'cafactor-v1', now(), :r)"""),
            {"c": ca, "k": W.C, "kn": kn, "r": rid})
        n = len(W.history())
        await W.insert_basis(s, sha)
        await W.insert_bar(s, ids, W.C, W.SESSION, W.close_of(W.C, n), rid=rid, sha=sha, i=n)
        await s.commit()
        before = by(await E.compute_snapshot(s, await snap(s), [W.C], with_context=False))
        assert before[(W.C, "ret_20d")] == (ok(W.close_of(W.C, n - 1)
                                                  / W.close_of(W.C, n - 21) - 1)[0], None)
        clock.freeze(W.ist(2026, 9, 25, 12))
        after = by(await E.compute_snapshot(s, await snap(s, day=_dt.date(2026, 9, 25)), [W.C],
                                            with_context=False))
        # the 20-sessions-earlier bar predates the ex-date: now divided by 2
        assert after[(W.C, "ret_20d")] == (ok(W.close_of(W.C, n)
                                                 / (W.close_of(W.C, n - 20) / 2) - 1)[0], None)

    async def test_low_confidence_bars_are_refused_never_used(self, world):
        res = await E.compute_snapshot(world, await snap(world), [W.E], with_context=False)
        v = by(res)
        usable = sum(1 for d in W.history() if d >= W.BONUS_EX)        # the CA horizon
        assert res.refused_bars["low_confidence"] == len(W.history()) - usable
        assert v[(W.E, "sma_20")] == (None, "INSUFFICIENT_HISTORY")
        assert v[(W.E, "ret_5d")][1] is None


# ── point in time ────────────────────────────────────────────────────────────
class TestPointInTime:
    async def _late_facts(self, s, at):
        """Facts knowable exactly at / after `at`: none may change a value."""
        ids = s.info["ids"]
        rid = await _run(s, "facts.after", source="UPSTOX_REST_V2")
        sha = await _payload(s, rid, "UPSTOX_REST_V2")
        # the snapshot session's own bar, even with an (impossible) early knowable_at
        await W.insert_basis(s, sha)
        await W.insert_bar(s, ids, W.A, W.SESSION, 999.0, rid=rid, sha=sha,
                           knowable=W.ist(2026, 9, 24, 8, 0))
        await s.execute(text("""
            insert into fundamental_snapshot (instrument_key, isin, statement_type, payload,
              source, run_id, payload_sha256, fetched_at, knowable_at, knowable_at_verified,
              knowable_at_basis) values (:k, 'INE000A00001', 'key_ratios', cast(:p as jsonb),
              'UPSTOX_REST_V2', :r, :h, :t, :t, false, 'fetched')"""),
            {"k": W.A, "p": json.dumps([{"name": "P/E", "company_value": "99"}]), "r": rid,
             "h": sha, "t": at})
        nid = (await s.execute(text("""
            insert into news_article (headline, published_at, headline_sha256, vendor_payload,
              source, run_id, payload_sha256, fetched_at, knowable_at, knowable_at_verified,
              knowable_at_basis) values ('late', :p, :hs, '{}', 'UPSTOX_REST_V2', :r, :h, :p,
              :p, true, 'published') returning id"""),
            {"p": at, "hs": "9" * 64, "r": rid, "h": sha})).scalar()
        await s.execute(text("""
            insert into news_instrument (news_id, instrument_key, source, run_id, payload_sha256,
              fetched_at, knowable_at, knowable_at_verified, knowable_at_basis)
            values (:n, :k, 'UPSTOX_REST_V2', :r, :h, :t, :t, false, 'link')"""),
            {"n": nid, "k": W.A, "r": rid, "h": sha, "t": at})
        await s.execute(text("""
            insert into preopen_tick (session_date, instrument_key, instrument_id, frame_seq,
              vendor_ts, feed_type, request_mode, iep, ieq, tbq, tsq, iiq_total, source, run_id,
              payload_sha256, fetched_at, knowable_at, knowable_at_verified, knowable_at_basis)
            values (:d, :k, :i, 2, :t, 'ff', 'full', 1.0, 1, 1, 99, 0, 'UPSTOX_WS_V3', :r, :h,
                    :t, :t, true, 'currentTs')"""),
            {"d": W.SESSION, "k": W.A, "i": ids[W.A], "t": at, "r": rid, "h": sha})
        await s.commit()

    @pytest.mark.parametrize("kind,at", [("PRE_SESSION", PRE_SESSION_AT),
                                         ("PRE_OPEN", PRE_OPEN_AT)])
    async def test_look_ahead_probe(self, world, kind, at):
        sn = await snap(world, kind)
        base = by(await E.compute_snapshot(world, sn, [W.A]))
        await self._late_facts(world, at)                        # knowable_at == as_of
        assert by(await E.compute_snapshot(world, sn, [W.A])) == base

    async def test_knowable_boundary_one_microsecond(self, world):
        sn = await snap(world)
        rid = await _run(world, "facts.edge", source="UPSTOX_REST_V2")
        sha = await _payload(world, rid, "UPSTOX_REST_V2")
        for pe, t in (("7", sn.as_of - _dt.timedelta(microseconds=1)), ("9", sn.as_of)):
            await world.execute(text("""
                insert into fundamental_snapshot (instrument_key, isin, statement_type, payload,
                  source, run_id, payload_sha256, fetched_at, knowable_at, knowable_at_verified,
                  knowable_at_basis) values (:k, 'INE000C00001', 'key_ratios',
                  cast(:p as jsonb), 'UPSTOX_REST_V2', :r, :h, :t, :t, false, 'fetched')"""),
                {"k": W.C, "p": json.dumps([{"name": "P/E", "company_value": pe}]), "r": rid,
                 "h": sha, "t": t})
        await world.commit()
        v = by(await E.compute_snapshot(world, sn, [W.C], with_context=False))
        assert v[(W.C, "pe")] == (7.0, None)

    async def test_previous_session_bar_missing_is_never_replaced_by_an_older_one(self, world):
        """At 2026-09-25 no stock has a 09-24 bar: bar features are MISSING_INPUT,
        not the 09-23 values relabelled."""
        clock.freeze(W.ist(2026, 9, 25, 12))
        v = by(await E.compute_snapshot(world, await snap(world, day=_dt.date(2026, 9, 25)),
                                        [W.A]))
        for f in ("ret_1d", "sma_20", "rsi_14", "avg_volume_20", "beta_60", "sector_rs_20"):
            assert v[(W.A, f)] == (None, "MISSING_INPUT"), f
        assert v[(W.NIFTY, "index_ret_1d")] == (None, "MISSING_INPUT")
        assert v[(W.A, "pe")] == (20.0, None)                       # non-bar features stand

    async def test_an_overclaiming_input_fails_loud(self, world, monkeypatch):
        sn = await snap(world)
        real = pit.fundamentals

        async def leaky(s, key, as_of, *a, **k):
            rows = await real(s, key, as_of, *a, **k)
            return [*rows, {**rows[0], "knowable_at": as_of}] if rows else rows
        monkeypatch.setattr(pit, "fundamentals", leaky)
        with pytest.raises(I.LookAhead):
            await E.compute_snapshot(world, sn, [W.A])


# ── the locked production path ───────────────────────────────────────────────
async def run(s, kind="PRE_SESSION", keys=(W.A, W.B, W.DD), mode="RUN", token=TOKEN):
    return await E.run_snapshot(s, await snap(s, kind), keys=list(keys) if keys else None,
                                mode=mode, token=token, operator="pytest")


async def stored(s):
    return await count(s, "select count(*) from feature_value")


async def events(s, ev=None):
    return await count(s, "select count(*) from stage3_event "
                          "where cast(:e as text) is null or event = :e", e=ev)


class TestRun:
    async def test_run_writes_then_rerun_is_idempotent(self, world, unlocked):
        r1 = await run(world)
        assert r1["committed"] and r1["inserted"] == r1["rows"] > 0
        assert await stored(world) == r1["rows"]
        r2 = await run(world)
        assert r2["inserted"] == 0 and r2["already_present"] == r1["rows"]
        assert await stored(world) == r1["rows"]
        assert await count(world, """select count(*) from ingest_run where stream =
            'features.PRE_SESSION' and status = 'COMPLETE'""") == 2
        assert await events(world, "RUN_COMPLETE") == 2
        row = (await world.execute(text("""select value, reason, registry_sha256, as_of,
            input_max_knowable_at from feature_value where instrument_key = :k and
            feature_id = 'pe'"""), {"k": W.A})).one()
        assert float(row.value) == 20.0 and row.reason is None
        assert row.input_max_knowable_at < row.as_of

    async def test_both_snapshots_are_separate_rows(self, world, unlocked):
        a, b = await run(world), await run(world, "PRE_OPEN")
        assert await stored(world) == a["rows"] + b["rows"]
        assert b["rows"] > a["rows"]                                 # + pre-open features

    async def test_determinism_mismatch_never_overwrites(self, world, unlocked):
        await run(world)
        n = await stored(world)
        rid = await _run(world, "facts.backdated", source="UPSTOX_REST_V2")
        sha = await _payload(world, rid, "UPSTOX_REST_V2")
        await world.execute(text("""
            insert into fundamental_snapshot (instrument_key, isin, statement_type, payload,
              source, run_id, payload_sha256, fetched_at, knowable_at, knowable_at_verified,
              knowable_at_basis) values (:k, 'INE000A00001', 'key_ratios', cast(:p as jsonb),
              'UPSTOX_REST_V2', :r, :h, :t, :t, false, 'fetched')"""),
            {"k": W.A, "p": json.dumps([{"name": "P/E", "company_value": "30"}]), "r": rid,
             "h": sha, "t": W.ist(2026, 9, 5)})
        await world.commit()
        with pytest.raises(E.DeterminismMismatch):
            await run(world)
        assert await stored(world) == n
        assert float((await world.execute(text("""select value from feature_value where
            instrument_key = :k and feature_id = 'pe'"""), {"k": W.A})).scalar()) == 20.0
        assert await events(world, "RUN_FAILED") == 1
        assert await count(world, """select count(*) from ingest_run where stream like
            'features.%' and status = 'FAILED'""") == 1

    async def test_exception_rolls_back_then_retry_succeeds(self, world, unlocked, monkeypatch):
        real = E.persist

        async def boom(s, res, run_id):
            await real(s, res, run_id)                               # rows staged ...
            raise RuntimeError("disk full")                          # ... then a failure
        monkeypatch.setattr(E, "persist", boom)
        with pytest.raises(RuntimeError):
            await run(world)
        assert await stored(world) == 0                              # rolled back
        monkeypatch.setattr(E, "persist", real)
        r = await run(world)                                         # retry
        assert r["inserted"] == r["rows"] == await stored(world)

    async def test_crash_is_reaped_and_the_rerun_completes(self, world, unlocked):
        dead = {"host": socket.gethostname(), "pid": 2 ** 22 + 12345, "boot_id": None}
        rid = uuid.uuid4()
        await world.execute(text("""
            insert into ingest_run (run_id, source, stream, vendor_endpoint, request_params,
              code_git_sha, config_sha256, argv, operator, mode, status, authz_token_sha256,
              started_at, rows_written) values (:r, 'PRAJNA_STAGE3', 'features.PRE_SESSION',
              't', cast(:p as jsonb), 't', :c, ARRAY['pytest'], 'pytest', 'COMMIT', 'RUNNING',
              :a, :t, 0)"""),
            {"r": rid, "p": json.dumps({"runner": dead}), "c": "c" * 64, "a": "a" * 64,
             "t": W.NOW - _dt.timedelta(minutes=5)})
        await world.commit()
        rep = await reap_runs(world, commit=True, token=TOKEN, operator="pytest")
        assert str(rid) in [o["run_id"] for o in rep["orphans"]]
        assert await count(world, "select status from ingest_run where run_id = :r",
                           r=rid) == "ABORTED"
        r = await run(world)
        assert r["inserted"] == r["rows"]

    async def test_restart_resumes_without_duplicates(self, world, unlocked):
        first = await run(world, keys=(W.A,))
        second = await run(world, keys=(W.A, W.B, W.DD))
        assert second["already_present"] == first["rows"]
        assert second["inserted"] == second["rows"] - first["rows"]
        assert await stored(world) == second["rows"]

    async def test_kill_switch_mid_run(self, world, unlocked, monkeypatch):
        calls = {"n": 0}

        def engaged():
            calls["n"] += 1
            return calls["n"] > 2                                    # after the lock check
        monkeypatch.setattr(locks, "kill_switch_engaged", engaged)
        with pytest.raises(E.KillSwitchEngaged):
            await run(world)
        assert await stored(world) == 0 and await events(world, "RUN_FAILED") == 1

    async def test_storage_is_append_only_and_pit_checked(self, world, unlocked):
        await run(world, keys=(W.A,))
        with pytest.raises(DBAPIError, match="append-only"):
            async with world.begin_nested():
                await world.execute(text("update feature_value set value = 1"))
        with pytest.raises(DBAPIError, match="append-only"):
            async with world.begin_nested():
                await world.execute(text("delete from stage3_event"))
        with pytest.raises(DBAPIError, match="ck_feature_pit"):
            async with world.begin_nested():
                await world.execute(text("""
                    insert into feature_value (scope, instrument_key, session_date, snapshot,
                      as_of, feature_id, feature_version, registry_sha256, value,
                      inputs_sha256, input_max_knowable_at, computed_at, run_id)
                    select scope, instrument_key, session_date, snapshot, as_of, 'probe', 1,
                      registry_sha256, 1, inputs_sha256, as_of, computed_at, run_id
                    from feature_value limit 1"""))


# ── the locks, one condition at a time ───────────────────────────────────────
def _flag_off(st, mp):
    mp.setattr(st, "PRAJNA_STAGE3_ENABLED", False)


def _kill(st, mp):
    locks.set_kill_switch(True, "test")


def _stage1(st, mp):
    async def no(_s):
        return False, "NOT COMPLETE (test)"
    mp.setattr(locks, "stage1_status", no)


def _stage2(st, mp):
    mp.setattr(locks, "stage2_status", lambda *a, **k: (False, "FAIL (test)"))


def _pending(st, mp):
    mp.setitem(DECISIONS["FEATURE-PARAMS"], "status", "PENDING")


class TestLocks:
    @pytest.mark.parametrize("breaker,name", [
        (_flag_off, "stage3_enabled"), (_kill, "kill_switch_off"),
        (_stage1, "stage1_complete"), (_stage2, "stage2_pass"),
        (_pending, "decisions_approved")])
    async def test_each_condition_alone_refuses_the_run(self, world, unlocked, monkeypatch,
                                                        breaker, name):
        breaker(unlocked, monkeypatch)
        with pytest.raises(locks.LockRefused) as e:
            await run(world)
        assert e.value.report.summary()["failing"] == [name]
        assert await stored(world) == 0
        assert await count(world, "select count(*) from ingest_run where stream like "
                                  "'features.%'") == 0
        ev = (await world.execute(text("select event, mode, detail from stage3_event"))).one()
        assert ev.event == "REFUSED" and ev.mode == "RUN"
        assert [c["name"] for c in ev.detail["conditions"] if not c["ok"]] == [name]

    async def test_bad_token_refuses(self, world, unlocked):
        with pytest.raises(locks.LockRefused) as e:
            await run(world, token="wrong")
        assert e.value.report.summary()["failing"] == ["write_token"]

    async def test_defaults_refuse_everything(self, world):
        """No test overrides: the real defaults (flag off; Stage 1 not evaluated COMPLETE
        on the seed world)."""
        with pytest.raises(locks.LockRefused) as e:
            await run(world)
        failing = e.value.report.summary()["failing"]
        assert "stage3_enabled" in failing and "decisions_approved" not in failing

    async def test_backfill_needs_its_own_flag(self, world, unlocked, monkeypatch):
        with pytest.raises(locks.LockRefused) as e:
            await run(world, mode="BACKFILL")
        assert e.value.report.summary()["failing"] == ["backfill_enabled"]
        monkeypatch.setattr(unlocked, "PRAJNA_STAGE3_BACKFILL_ENABLED", True)
        assert (await run(world, mode="BACKFILL"))["committed"]

    async def test_dry_run_needs_no_lock_and_writes_nothing(self, world):
        res = await E.compute_snapshot(world, await snap(world), [W.A])
        assert res.rows and await stored(world) == 0 and await events(world) == 0


# ── FII/DII staleness (decision FII-DII-STALENESS) ──────────────────────────────
async def _fii(s, day, buy, sell, knowable):
    rid = await _run(s, f"macro.{uuid.uuid4().hex[:6]}", source="UPSTOX_REST_V2")
    sha = await _payload(s, rid, "UPSTOX_REST_V2")
    for side, v in (("buy_amt", buy), ("sell_amt", sell)):
        await s.execute(text("""
            insert into macro_observation (series_code, observation_date, value, unit,
              vendor_payload, source, run_id, payload_sha256, fetched_at, knowable_at,
              knowable_at_verified, knowable_at_basis)
            values (:c, :d, :v, 'INR_vendor', '{}', 'UPSTOX_REST_V2', :r, :h, :k, :k, false,
                    'fetched')"""),
            {"c": f"FII|NSE_EQ|CASH|1D|{side}", "d": day, "v": v, "r": rid, "h": sha,
             "k": knowable})


class TestFiiDiiStaleness:
    async def test_publication_after_as_of_is_not_used_and_no_older_day_is_relabelled(
            self, world):
        """09-22 knowable 09-23 08:30; 09-23 knowable 09-24 09:05 IST - after PRE_SESSION
        (08:59:59) and before PRE_OPEN (09:08:00). Previous session of 09-24 is 09-23."""
        await _fii(world, _dt.date(2026, 9, 22), 100, 40, W.ist(2026, 9, 23, 8, 30))
        await _fii(world, _dt.date(2026, 9, 23), 50, 80, W.ist(2026, 9, 24, 9, 5))
        await world.commit()
        ps, po = await snap(world), await snap(world, "PRE_OPEN")
        assert ps.previous_session == _dt.date(2026, 9, 23)
        a = by(await E.compute_snapshot(world, ps, [W.A]))
        assert a[("MARKET", "fii_net_cash_1d")] == (None, "MISSING_INPUT")   # not 09-22's 60
        b = by(await E.compute_snapshot(world, po, [W.A]))
        assert b[("MARKET", "fii_net_cash_1d")] == (-30.0, None)             # 09-23 visible
        assert b[("MARKET", "fii_net_cash_5d")] == (None, "INSUFFICIENT_HISTORY")

    async def test_holiday_boundary_uses_the_calendar_previous_session(self, world):
        """Snapshot Monday 2026-09-14: previous session Friday 09-11 (weekend between)."""
        clock.freeze(W.ist(2026, 9, 14, 12))
        await _fii(world, _dt.date(2026, 9, 11), 70, 20, W.ist(2026, 9, 12, 9, 0))
        await world.commit()
        sn = await snap(world, day=_dt.date(2026, 9, 14))
        assert sn.previous_session == _dt.date(2026, 9, 11)
        v = by(await E.compute_snapshot(world, sn, [W.A]))
        assert v[("MARKET", "fii_net_cash_1d")] == (50.0, None)


# ── one consistent database snapshot per run ─────────────────────────────────
class Concurrent:
    """Another client on its own connection: what it commits is visible to every
    new transaction at once. It removes exactly what it committed afterwards."""

    def __init__(self):
        from sqlalchemy.ext.asyncio import create_async_engine

        from tests.conftest import TEST_DSN
        self.engine = create_async_engine(TEST_DSN, poolclass=None)
        self.runs: list[uuid.UUID] = []

    async def commit_fii(self, day, buy, sell, knowable):
        async with self.engine.begin() as c:
            from sqlalchemy.ext.asyncio import AsyncSession
            s = AsyncSession(bind=c)
            await _fii(s, day, buy, sell, knowable)
            self.runs += [r for (r,) in (await s.execute(text(
                "select run_id from ingest_run where stream like 'macro.%'"))).all()
                if r not in self.runs]
            await s.flush()

    async def visible(self, sql, **kw):
        async with self.engine.connect() as c:          # a new READ COMMITTED transaction
            return (await c.execute(text(sql), kw)).scalar()

    async def close(self):
        async with self.engine.begin() as c:
            for r in self.runs:
                await c.execute(text("delete from macro_observation where run_id = :r"), {"r": r})
                await c.execute(text("delete from raw_payload where first_seen_run = :r"),
                                {"r": r})
                await c.execute(text("delete from ingest_run where run_id = :r"), {"r": r})
        await self.engine.dispose()


@pytest.fixture
async def concurrent():
    c = Concurrent()
    try:
        yield c
    finally:
        await c.close()


class TestSnapshotConsistency:
    async def test_a_commit_during_the_run_is_not_observed(self, world, unlocked, concurrent,
                                                           monkeypatch):
        """The run starts reading (the benchmark index, then the first instrument); a
        concurrent transaction then commits the FII/DII figure of 09-23, knowable
        09-24 08:00 IST - before PRE_SESSION as_of 08:59:59, so a fresh read would use
        it. The run continues and must still see the state it started from: FII/DII
        MISSING_INPUT, as when it began, with no mix of the two states."""
        real, calls = I.instrument_inputs, {"n": 0}

        async def mid_run(s, key, sn):
            calls["n"] += 1
            if calls["n"] == 2:                  # the run has read the index and W.A
                await concurrent.commit_fii(_dt.date(2026, 9, 23), 100, 40,
                                            W.ist(2026, 9, 24, 8))
            return await real(s, key, sn)
        monkeypatch.setattr(I, "instrument_inputs", mid_run)
        r = await run(world)
        assert calls["n"] > 2 and r["committed"] is True       # committed mid-run
        assert await concurrent.visible(
            "select count(*) from macro_observation where observation_date = '2026-09-23'") == 2
        stored_fii = (await world.execute(text("""select value, reason from feature_value
            where feature_id = 'fii_net_cash_1d'"""))).one()
        assert tuple(stored_fii) == (None, "MISSING_INPUT")    # not 60.0 from the late commit

    async def test_the_production_session_sets_repeatable_read_itself(self, concurrent):
        """Outside the test harness (a plain session, as the CLI and cron use), the run's
        transaction is REPEATABLE READ and keeps its first-read state across a
        concurrent commit; the dry-run's is also READ ONLY."""
        from sqlalchemy.ext.asyncio import AsyncSession
        n_sql = "select count(*) from macro_observation where observation_date = '2026-09-23'"
        async with concurrent.engine.connect() as conn:
            s = AsyncSession(bind=conn)
            assert await E.consistent_read(s, read_only=False) == "repeatable read"
            before = (await s.execute(text(n_sql))).scalar()
            await concurrent.commit_fii(_dt.date(2026, 9, 23), 100, 40, W.ist(2026, 9, 24, 8))
            assert (await s.execute(text(n_sql))).scalar() == before       # same snapshot
            assert await concurrent.visible(n_sql) == before + 2           # committed
            await s.commit()
            assert (await s.execute(text(n_sql))).scalar() == before + 2   # next transaction
            await s.commit()
            assert await E.consistent_read(s, read_only=True) == "repeatable read"
            assert (await s.execute(text("show transaction_read_only"))).scalar() == "on"
            await s.rollback()

    @pytest.mark.isolation("READ COMMITTED")
    async def test_a_run_refuses_without_a_consistent_snapshot(self, world, unlocked):
        with pytest.raises(E.SnapshotIsolationError):
            await run(world)
        assert await stored(world) == 0 and await events(world, "RUN_FAILED") == 1


# ── adversarial point in time: each input knowable just after as_of ──────────
# (already covered elsewhere, not repeated: the snapshot session's own bar -
# TestPointInTime._late_facts; FII/DII published after as_of - TestFiiDiiStaleness;
# a NEW split knowable after as_of - TestPriceBasis)
LATE = W.ist(2026, 9, 24, 9, 5)          # after PRE_SESSION 08:59:59, before PRE_OPEN 09:08


async def _facts(s, stream):
    rid = await _run(s, stream, source="UPSTOX_REST_V2")
    return rid, await _payload(s, rid, "UPSTOX_REST_V2")


class TestAdversarialPointInTime:
    async def test_late_bar_revision_is_never_used(self, world):
        """A's 09-23 bar (close 100 + n, knowable 09-23 16:00 IST) is re-served with close
        999: once observed at 09-24 08:00 (before as_of) and once at 09:30 (after). The
        first observation wins (Stage 1 D3): revisions live in ohlcv_observation, which
        no Stage 3 input reads, so ret_1d stays the first observation's at both as_of."""
        n = len(W.history()) - 1
        rid, sha = await _facts(world, "bars.revision")
        for fetched in (W.ist(2026, 9, 24, 8), W.ist(2026, 9, 24, 9, 30)):
            await world.execute(text("""
                insert into ohlcv_observation (instrument_id, timeframe, session_date,
                  bar_start_utc, source, instrument_key, open, high, low, close, volume,
                  run_id, payload_sha256, fetched_at, classification, reason, method_version)
                values (:i, '1d', '2026-09-23', :b, 'UPSTOX_REST_V3', :k, 998, 1000, 997, 999,
                        1, :r, :h, :f, 'ROUNDING', 'adversarial test', 'revision-v1')"""),
                {"i": world.info["ids"][W.A], "b": W.ist(2026, 9, 23), "k": W.A, "r": rid,
                 "h": sha, "f": fetched})
        await world.commit()
        want = (ok((100 + n) / (99 + n) - 1)[0], None)
        for kind, at in (("PRE_SESSION", PRE_SESSION_AT), ("PRE_OPEN", PRE_OPEN_AT)):
            sn = await snap(world, kind)
            assert sn.as_of == at
            res = await E.compute_snapshot(world, sn, [W.A], with_context=False)
            assert by(res)[(W.A, "ret_1d")] == want, kind
            row = next(r for r in res.rows if r.feature_id == "ret_1d")
            assert row.input_max_knowable_at == W.ist(2026, 9, 23, 16)   # the stored bar

    async def test_previous_session_bar_first_observed_after_as_of(self, world):
        """Snapshot 2026-09-25 (previous session 09-24). A's 09-24 bar is first knowable
        09-25 09:05: invisible at PRE_SESSION 08:59:59 -> MISSING_INPUT (never 09-23
        relabelled); visible at PRE_OPEN 09:08:00 -> ret_1d from it."""
        clock.freeze(W.ist(2026, 9, 25, 12))
        n = len(W.history())
        rid, sha = await _facts(world, "bars.late")
        await W.insert_basis(world, sha)
        kn = W.ist(2026, 9, 25, 9, 5)
        await W.insert_bar(world, world.info["ids"], W.A, W.SESSION, W.close_of(W.A, n),
                           rid=rid, sha=sha, knowable=kn, i=n)
        await world.commit()
        day = _dt.date(2026, 9, 25)
        ps, po = await snap(world, day=day), await snap(world, "PRE_OPEN", day)
        assert ps.as_of == W.ist(2026, 9, 25, 8, 59, 59) and po.as_of == W.ist(2026, 9, 25, 9, 8)
        assert ps.previous_session == W.SESSION
        a = by(await E.compute_snapshot(world, ps, [W.A], with_context=False))
        assert a[(W.A, "ret_1d")] == (None, "MISSING_INPUT")
        res = await E.compute_snapshot(world, po, [W.A], with_context=False)
        assert by(res)[(W.A, "ret_1d")] == (ok((100 + n) / (99 + n) - 1)[0], None)
        row = next(r for r in res.rows if r.feature_id == "ret_1d")
        assert row.input_max_knowable_at == kn

    async def test_revised_corporate_action_known_after_as_of(self, world):
        """B's 1:1 bonus (ex 09-10, factor 2, knowable 08-20) is revised by the vendor to
        2:1 (factor 3), the revision knowable 09-24 09:05. At PRE_SESSION 08:59:59 only
        the original is known: B's adjusted prices still equal A's feature for feature,
        and the revision is not among the events used."""
        sn = await snap(world)
        base = by(await E.compute_snapshot(world, sn, [W.A, W.B], with_context=False))
        rid, sha = await _facts(world, "facts.ca_revision")
        ca = (await world.execute(text("""
            insert into corporate_action (isin, instrument_key, trading_symbol, action_type,
              ex_date, announcement_date, ratio_from, ratio_to, content_sha256, vendor_payload,
              source, run_id, payload_sha256, fetched_at, knowable_at, knowable_at_verified,
              knowable_at_basis)
            values ('INE000B00001', :k, 'X', 'BONUS', :x, '2026-08-20', 2, 1, :c, '{}',
                    'UPSTOX_REST_V2', :r, :h, :kn, :kn, false, 'KN-CA') returning id"""),
            {"k": W.B, "x": W.BONUS_EX, "c": uuid.uuid4().hex * 2, "r": rid, "h": sha,
             "kn": LATE})).scalar()
        await world.execute(text("""
            insert into ca_factor (ca_id, instrument_key, action_type, ex_date, status, method,
              factor_price, factor_volume, knowable_at, vendor_applied, reason, method_version,
              derived_at, run_id) values (:c, :k, 'BONUS', :x, 'EXACT', 'BONUS_RATIO', 3, 3,
              :kn, 'NOT_APPLIED', 'revision', 'cafactor-v1', now(), :r)"""),
            {"c": ca, "k": W.B, "x": W.BONUS_EX, "kn": LATE, "r": rid})
        await world.commit()
        v = by(await E.compute_snapshot(world, sn, [W.A, W.B], with_context=False))
        assert v == base
        for f in ("ret_20d", "sma_20", "sma_50", "volatility_20"):
            assert v[(W.B, f)] == v[(W.A, f)], f
        adj = await pit.bars_adjusted(world, W.B, "1d", sn.as_of)
        assert adj["events_known"] == [world.info["ids"]["bonus_ca"]]         # not `ca`
        po = await snap(world, "PRE_OPEN")                   # 09:08:00: the revision is known
        assert ca in (await pit.bars_adjusted(world, W.B, "1d", po.as_of))["events_known"]

    async def test_delayed_financial_statement(self, world):
        """A's quarterly income statement with Jun 2026 (130 vs Jun 2025 100) arrives late:
        knowable 09-24 09:05. PRE_SESSION uses the statement stored on 09-01 (quarterly
        figures labelled a year apart: MALFORMED_INPUT); PRE_OPEN uses the new one (0.3)."""
        rid, sha = await _facts(world, "facts.statement")
        await world.execute(text("""
            insert into fundamental_snapshot (instrument_key, isin, statement_type, payload,
              source, run_id, payload_sha256, fetched_at, knowable_at, knowable_at_verified,
              knowable_at_basis) values (:k, 'INE000A00001', 'income:consolidated:quarterly',
              cast(:p as jsonb), 'UPSTOX_REST_V2', :r, :h, :t, :t, false, 'fetched')"""),
            {"k": W.A, "p": json.dumps(W._stmt({"Revenue": {
                "Jun 2026": 130, "Mar 2026": 120, "Jun 2025": 100}}, "quarterly")),
             "r": rid, "h": sha, "t": LATE})
        await world.commit()
        ps, po = await snap(world), await snap(world, "PRE_OPEN")
        a = by(await E.compute_snapshot(world, ps, [W.A], with_context=False))
        assert a[(W.A, "revenue_yoy_q")] == (None, "MALFORMED_INPUT")
        assert a[(W.A, "revenue_yoy")] == (0.2, None)              # yearly: unchanged
        b = by(await E.compute_snapshot(world, po, [W.A], with_context=False))
        assert b[(W.A, "revenue_yoy_q")] == (ok(130 / 100 - 1)[0], None)

    async def test_india_vix_previous_session_missing(self, world):
        """Snapshot 2026-09-25: VIX's last stored bar is 09-23. Its 09-24 bar is first
        knowable 09-25 09:05. PRE_SESSION: MISSING_INPUT (09-23's level is not
        relabelled); PRE_OPEN: the 09-24 level."""
        clock.freeze(W.ist(2026, 9, 25, 12))
        day, n = _dt.date(2026, 9, 25), len(W.history())
        ps = await snap(world, day=day)
        v = by(await E.compute_snapshot(world, ps, [W.A]))
        assert v[(W.VIX, "india_vix_level")] == (None, "MISSING_INPUT")
        assert v[(W.VIX, "india_vix_change_5d")] == (None, "MISSING_INPUT")
        rid, sha = await _facts(world, "bars.vix")
        await W.insert_basis(world, sha)
        await W.insert_bar(world, world.info["ids"], W.VIX, W.SESSION, W.close_of(W.VIX, n),
                           rid=rid, sha=sha, knowable=W.ist(2026, 9, 25, 9, 5), i=n)
        await world.commit()
        v = by(await E.compute_snapshot(world, ps, [W.A]))
        assert v[(W.VIX, "india_vix_level")] == (None, "MISSING_INPUT")
        po = by(await E.compute_snapshot(world, await snap(world, "PRE_OPEN", day), [W.A]))
        assert po[(W.VIX, "india_vix_level")] == (ok(W.close_of(W.VIX, n))[0], None)


class TestPersistScale:
    """BUG-STAGE3-PERSIST-PARAM-LIMIT: one multi-row INSERT binds rows x 15 parameters
    and asyncpg allows 32,767; 5,000-row chunks (75,000) failed on the real universe
    (180,919 rows, 2026-09-28). Found by measuring persistence; the seed world's
    ~275 rows never crossed the limit."""

    def test_bind_parameters_per_row_are_counted_from_the_real_statement(self):
        from sqlalchemy.dialects.postgresql import asyncpg as pg_asyncpg
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from app.db.models import FeatureValue
        row = {c.name: None for c in FeatureValue.__table__.columns if c.name != "id"}

        def binds(n):
            st = pg_insert(FeatureValue).values([dict(row) for _ in range(n)])
            return len(st.on_conflict_do_nothing(constraint="uq_feature_value")
                       .compile(dialect=pg_asyncpg.dialect()).positiontup)
        assert binds(1) == len(row) == 15
        assert binds(E.batch_rows(15)) == 30000 <= E.PARAM_BUDGET < E.ASYNCPG_MAX_BIND_PARAMS
        assert binds(E.batch_rows(15) + 1) > E.PARAM_BUDGET
        assert binds(5000) == 75000 > E.ASYNCPG_MAX_BIND_PARAMS          # the old chunk
        assert E.batch_rows(10 ** 6) == 1

    async def test_rows_across_several_batches_persist_then_rerun_is_idempotent(self, world):
        """5,000 rows: the old single-chunk failure boundary (> 2,184 rows) crossed, and
        3 batches at 2,000; then the rerun finds all present, a changed value fails
        the determinism check, and nothing is overwritten or duplicated."""
        sn = await snap(world)
        res = await E.compute_snapshot(world, sn, [W.A], with_context=False)
        base = [r for r in res.rows if r.scope == "INSTRUMENT"]
        rows = [E.FeatureRow(r.scope, f"NSE_EQ|SCALE{i:05d}", r.feature_id, r.value, r.reason,
                             r.inputs_sha256, r.input_max_knowable_at)
                for i in range(-(-5000 // len(base))) for r in base][:5000]
        res.rows = rows
        seen = []

        def spy(conn, cursor, statement, params, context, executemany):
            if statement.lstrip().lower().startswith("insert into feature_value"):
                seen.append(len(params))
        from sqlalchemy import event
        sync = world.bind.sync_engine
        event.listen(sync, "before_cursor_execute", spy)
        try:
            rid = await _run(world, "features.scale", source="PRAJNA_STAGE3")
            assert await E.persist(world, res, rid) == (5000, 0)
        finally:
            event.remove(sync, "before_cursor_execute", spy)
        assert seen == [30000, 30000, 15000]                     # parameters per statement
        assert await E.persist(world, res, rid) == (0, 5000)
        assert await count(world, """select count(*) from (select 1 from feature_value
            group by instrument_key, session_date, snapshot, feature_id having count(*) > 1)
            x""") == 0
        i = next(i for i, r in enumerate(rows) if r.value is not None)
        res.rows = [*rows[:i], E.FeatureRow(rows[i].scope, rows[i].instrument_key,
                    rows[i].feature_id, rows[i].value + 1, None, rows[i].inputs_sha256,
                    rows[i].input_max_knowable_at), *rows[i + 1:]]
        with pytest.raises(E.DeterminismMismatch):
            await E.persist(world, res, rid)
        assert await count(world, "select count(*) from feature_value") == 5000

    async def test_a_failure_after_a_batch_leaves_no_partial_snapshot(self, world, unlocked,
                                                                     monkeypatch):
        """A run whose persistence fails after its first INSERT batch is committed has
        written nothing: the run is FAILED and 0 feature values remain."""
        real, n = E.persist, {"batches": 0}

        async def failing(s, res, run_id):
            rows = res.rows
            res.rows = rows * 40                             # > 1 batch of 2,000 rows
            from sqlalchemy import event

            def after(*a):
                n["batches"] += 1
                if n["batches"] == 2:
                    raise RuntimeError("injected failure after 1 committed-in-tx batch")
            event.listen(s.bind.sync_engine, "after_cursor_execute", after)
            try:
                return await real(s, res, run_id)
            finally:
                event.remove(s.bind.sync_engine, "after_cursor_execute", after)
                res.rows = rows
        monkeypatch.setattr(E, "persist", failing)
        with pytest.raises(RuntimeError, match="injected"):
            await run(world)
        assert n["batches"] >= 2 and await stored(world) == 0
        assert await events(world, "RUN_FAILED") == 1
