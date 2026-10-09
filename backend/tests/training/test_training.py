"""Stage 4 training data on the Stage 3 seed world (tests/support/stage3_seed.py):
the replay reuses the production engine; the missingness contract (a history
never collected is NOT_AVAILABLE_HISTORICALLY, never 0); resume and idempotency;
the AS_IF_LIVE shadow views (visible only with their search_path, never to
production readers); label-v1 values, corporate-action basis and timing.
Test database only; no network."""

from __future__ import annotations

import datetime as _dt
import os

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.canon import process as CP
from app.core import clock
from app.features import engine as E
from app.features import snapshots as SN
from app.features.compute import ok
from app.training import availability as A
from app.training import labels as L
from app.training import policy as P
from app.training import replay as RP
from tests.support import stage3_seed as W
from tests.support.stage2_seed import _payload, _run

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.isolation("REPEATABLE READ")]
TOKEN = os.environ["PRAJNA_WRITE_TOKEN"]
STRICT, ASIF = P.DATASETS["strict"], P.DATASETS["asif"]
F = "NSE_EQ|INE000F00001"


@pytest.fixture
async def world(db_session):
    clock.freeze(W.NOW)
    ids = await W.seed(db_session)
    await CP.process(db_session, commit=True, token=TOKEN)
    db_session.info["ids"] = ids
    yield db_session
    clock.unfreeze()


async def snap(s, kind="PRE_SESSION", day=W.SESSION):
    return await SN.resolve(s, day, kind)


async def stored(s, ds, day=W.SESSION, kind="PRE_SESSION"):
    return {(r[0], r[1]): (r[2], r[3], r[4]) for r in (await s.execute(text("""
        select instrument_key, feature_id, value, status, reason from training_feature_value
        where dataset_version = :v and session_date = :d and snapshot = :k"""),
        {"v": ds.version, "d": day, "k": kind})).all()}


async def run(s, ds, sn, **kw):
    rid = await RP.open_run(s, ds, sn.session_date, sn.session_date, None, "test")
    return rid, await RP.replay_snapshot(s, ds, sn, rid, **kw)


async def add_stock_f(s, *, last_knowable=None, skip_last=False):
    """Stock F: A's prices; its 2026-09-23 bar absent (skip_last) or knowable late."""
    ids = s.info["ids"]
    rid = await _run(s, "instrument.f", source="UPSTOX_ASSETS")
    sha = await _payload(s, rid, "UPSTOX_ASSETS")
    ids[F] = (await s.execute(text("""insert into instrument (instrument_key, segment, exchange,
        trading_symbol, isin, instrument_type, valid_from, source, run_id, payload_sha256,
        fetched_at, knowable_at, knowable_at_basis) values (:k, 'NSE_EQ', 'NSE', 'FFF',
        'INE000F00001', 'EQ', '2026-05-01', 'UPSTOX_ASSETS', :r, :h, :f, :f, 't')
        returning instrument_id"""), {"k": F, "r": rid, "h": sha,
                                      "f": W.ist(2026, 5, 1)})).scalar()
    bars = await _run(s, "ohlcv.1d.f")
    bsha = await _payload(s, bars)
    hist = W.history()
    for i, day in enumerate(hist):
        if day == hist[-1] and skip_last:
            continue
        kn = last_knowable if day == hist[-1] else None
        await W.insert_bar(s, ids, F, day, 100 + i, rid=bars, sha=bsha, i=i, knowable=kn)
    await W.insert_basis(s, bsha)
    await CP.process(s, commit=True, token=TOKEN)


async def asif_params(s):
    rows = [("daily_bar", "next_session_ist", 8 * 3600 + 33 * 60),
            ("fii_dii", "next_session_ist", 8 * 3600 + 33 * 60),
            ("corporate_action", "after_ex", 2 * 86400)]
    for wd in range(1, 8):
        rows += [("global", f"first_wd{wd}", 36 * 3600 + 40 * 60),
                 ("global", f"confirm_wd{wd}", 45 * 3600 + 11 * 60)]
    for fam, key, sec in rows:
        await s.execute(text("""insert into training_policy_param (policy, family, key, seconds,
            basis, measured_at) values (:p, :f, :k, :s, 'test', now())"""),
            {"p": P.ASIF, "f": fam, "k": key, "s": sec})
    await s.commit()


# ── the replay is the production engine ─────────────────────────────────────────
class TestStrictReplay:
    async def test_values_equal_the_engine_and_the_contract(self, world):
        sn = await snap(world)
        _, rep = await run(world, STRICT, sn)
        got = await stored(world, STRICT)
        await E.consistent_read(world, read_only=True)
        keys, _ = await RP.universe(world, sn)
        res = await E.compute_snapshot(world, sn, keys)
        await world.rollback()
        assert rep["rows"] == len(res.rows) == len(got) and rep["inserted"] == len(got)
        for r in res.rows:
            v, st, why = got[(r.instrument_key, r.feature_id)]
            assert why == r.reason
            if st == A.VALID:
                assert v == r.value and r.reason is None
            else:
                assert v is None
        n = len(W.history()) - 1
        assert got[(W.A, "ret_1d")][:2] == (ok((100 + n) / (99 + n) - 1)[0], "VALID")
        assert got[(W.A, "sma_200")][1:] == ("MISSING_INPUT", "INSUFFICIENT_HISTORY")
        assert got[(W.DD, "pe")][1] == "INVALID"                       # malformed key_ratios
        # never collected before as_of: FII/DII, globals, multi-source news
        assert got[("MARKET", "fii_net_cash_1d")] == (None, A.NA_HIST, "MISSING_INPUT")
        assert got[("MARKET", "mnews_news_count_24h")][1] == A.NA_HIST
        assert got[(W.A, "mnews_company_count_24h")][1] == A.NA_HIST
        # collected (legacy news exists before as_of): 0 is a real zero
        assert got[(W.A, "news_count_24h")][:2] == (1.0, "VALID")
        assert got[(W.B, "news_count_24h")][:2] == (0.0, "VALID")
        assert not any(k[1].startswith("preopen_") for k in got)

    async def test_pre_open_snapshot(self, world):
        sn = await snap(world, "PRE_OPEN")
        await run(world, STRICT, sn)
        got = await stored(world, STRICT, kind="PRE_OPEN")
        assert got[(W.A, "preopen_imbalance")][:2] == (0.5, "VALID")
        assert got[(W.B, "preopen_ieq")][1] == "MISSING_INPUT"         # collected, B had none

    async def test_news_never_zero_before_collection(self, world):
        """2026-09-23 08:59:59: the legacy news feed's first article is knowable at 20:00
        that day. The engine computes 0 (an empty list); the dataset stores nothing."""
        day = _dt.date(2026, 9, 23)
        sn = await snap(world, day=day)
        await E.consistent_read(world, read_only=True)
        res = await E.compute_snapshot(world, sn, [W.B], with_context=False)
        await world.rollback()
        assert {r.feature_id: r.value for r in res.rows}["news_count_24h"] == 0.0
        await run(world, STRICT, sn)
        got = await stored(world, STRICT, day=day)
        assert got[(W.B, "news_count_24h")] == (None, A.NA_HIST, None)
        assert got[(W.B, "news_hours_since_last")][1] == A.NA_HIST

    async def test_stale_bar_is_stale_input(self, world):
        await add_stock_f(world, skip_last=True)
        sn = await snap(world)
        await run(world, STRICT, sn)
        got = await stored(world, STRICT)
        assert got[(F, "ret_1d")][:2] == (None, A.STALE)
        assert got[(W.A, "ret_1d")][1] == A.VALID

    async def test_resume_and_idempotency(self, world):
        sn = await snap(world)
        rid, first = await run(world, STRICT, sn)
        await RP.finish_run(world, rid, "COMPLETE")
        n = len(await stored(world, STRICT))
        _, again = await run(world, STRICT, sn)
        assert again["skipped"] == "done" and again["rows"] == first["rows"] == n
        assert len(await stored(world, STRICT)) == n
        r = (await world.execute(text("""select status, sessions_done, row_count
            from training_dataset_run where run_id = :r"""), {"r": rid})).one()
        assert tuple(r) == ("COMPLETE", 1, n)
        assert (await world.execute(text("select count(*) from feature_value"))).scalar() == 0

    async def test_rows_are_append_only_and_point_in_time(self, world):
        sn = await snap(world)
        rid, _ = await run(world, STRICT, sn)
        with pytest.raises(DBAPIError, match="append-only"):
            async with world.begin_nested():
                await world.execute(text("update training_feature_value set value = 1"))
        with pytest.raises(DBAPIError, match="ck_training_fv_pit"):
            async with world.begin_nested():
                await world.execute(text("""insert into training_feature_value
                    (dataset_version, session_date, snapshot, as_of, scope, instrument_key,
                     feature_id, feature_version, value, status, inputs_sha256,
                     input_max_knowable_at, run_id) values ('x', '2026-09-24', 'PRE_SESSION',
                     :a, 'INSTRUMENT', 'k', 'ret_1d', '1', 1, 'VALID', :h, :a, :r)"""),
                    {"a": sn.as_of, "h": "0" * 64, "r": rid})

    def test_statements_stay_under_the_bind_budget(self):
        assert E.batch_rows(len(RP.COLUMNS)) * len(RP.COLUMNS) <= E.PARAM_BUDGET < 32767
        assert E.batch_rows(len(L.COLUMNS)) * len(L.COLUMNS) <= E.PARAM_BUDGET


# ── corporate actions: knowable when Prajna observed them (STRICT_PIT-v2) ─────────
class TestCorporateActionKnowability:
    async def test_an_action_fetched_after_as_of_is_invisible(self, world):
        """C's split goes ex on 2026-10-01; it was announced 09-01 (KN-CA: knowable at the
        end of 09-01) but Prajna fetched it only on 09-30. Production views see it at
        the 09-24 snapshot only under KN-CA; since CA-OBSERVED (features-v3) they do not,
        like STRICT; AS_IF_LIVE assumes ex-date + the lag."""
        await asif_params(world)
        rid = await _run(world, "facts.late_ca", source="UPSTOX_REST_V2")
        sha = await _payload(world, rid, "UPSTOX_REST_V2")
        await world.execute(text("""insert into corporate_action (isin, instrument_key,
            trading_symbol, action_type, ex_date, announcement_date, content_sha256,
            vendor_payload, source, run_id, payload_sha256, fetched_at, knowable_at,
            knowable_at_verified, knowable_at_basis) values ('INE000C00001', :k, 'CCC',
            'SPLIT', '2026-10-01', '2026-09-01', :c, '{}', 'UPSTOX_REST_V2', :r, :h, :f, :kn,
            false, 'KN-CA')"""), {"k": W.C, "c": "c" * 64, "r": rid, "h": sha,
                                 "f": W.ist(2026, 9, 30, 10), "kn": W.ist(2026, 9, 1, 23, 59, 59)})
        await world.commit()
        sn = await snap(world)
        await E.consistent_read(world, read_only=True)
        prod = await E.compute_snapshot(world, sn, [W.C], with_context=False)
        await world.rollback()
        assert {r.feature_id: r.reason for r in prod.rows}["ca_days_to_split"] == "MISSING_INPUT"
        kn_ca = (await world.execute(text("""select count(*) from canon_corporate_action_kn_ca
            where instrument_key = :k and knowable_at < :a"""), {"k": W.C, "a": sn.as_of})).scalar()
        assert kn_ca == 1                        # under KN-CA it was visible (7 days to the split)
        await run(world, STRICT, sn)
        await run(world, ASIF, sn)
        assert (await stored(world, STRICT))[(W.C, "ca_days_to_split")][:2] == (
            None, "MISSING_INPUT")
        assert (await stored(world, ASIF))[(W.C, "ca_days_to_split")][:2] == (
            None, "MISSING_INPUT")                    # ex-date + 2 days is after as_of too


# ── AS_IF_LIVE: shadow views ─────────────────────────────────────────────────────
class TestAsIfLive:
    async def test_shadow_only_with_its_search_path(self, world):
        """F's 2026-09-23 bar was downloaded in bulk on 09-29. STRICT at 09-24 08:59:59
        cannot see it (stale); AS_IF_LIVE assumes the live schedule (next session +
        08:33 IST) and can. Production views never see the assumption."""
        await asif_params(world)
        await add_stock_f(world, last_knowable=W.ist(2026, 9, 29, 10))
        sn = await snap(world)
        q = text("""select knowable_at, knowable_at_basis from canon_market_bar
                    where instrument_key = :k and market_date = '2026-09-23'""")
        real = (await world.execute(q, {"k": F})).one()
        assert real[0] == W.ist(2026, 9, 29, 10)
        await run(world, STRICT, sn)
        await run(world, ASIF, sn)
        s_rows, a_rows = await stored(world, STRICT), await stored(world, ASIF)
        assert s_rows[(F, "ret_1d")][1] == A.STALE
        assert a_rows[(F, "ret_1d")][:2] == (s_rows[(W.A, "ret_1d")][0], A.VALID)
        assert a_rows[(W.A, "sma_20")] == s_rows[(W.A, "sma_20")]   # live rows: unchanged
        # after the replay the session is back on the production views
        assert (await world.execute(text("show search_path"))).scalar() == '"$user", public'
        assert (await world.execute(q, {"k": F})).one() == real
        await world.execute(text(f"set local search_path = {ASIF.search_path}"))
        shadow = (await world.execute(q, {"k": F})).one()
        await world.execute(text("set local search_path to default"))
        assert shadow[0] == W.ist(2026, 9, 24, 8, 33) and shadow[1].startswith("ASSUMED")
        assert (await world.execute(text("""select knowable_at from public.canon_market_bar
            where instrument_key = :k and market_date = '2026-09-23'"""),
            {"k": F})).scalar() == real[0]

    async def test_params_are_frozen(self, world):
        await asif_params(world)
        a = await P.ensure_params(world)
        b = await P.ensure_params(world)
        assert a == b and a["daily_bar.next_session_ist"]["seconds"] == 30780
        with pytest.raises(DBAPIError, match="append-only"):
            async with world.begin_nested():
                await world.execute(text("update training_policy_param set seconds = 0"))


# ── label-v1 ────────────────────────────────────────────────────────────────────
class TestLabels:
    async def test_values_basis_and_timing(self, world):
        hist = W.history()
        rep = await L.build(world, hist[0], hist[-1], [W.A, W.B])
        assert rep["inserted"] == rep["rows"] and rep["drift_vs_stored"] == 0
        lab = {(r[0], r[1], r[2]): (r[3], r[4], r[5]) for r in (await world.execute(text("""
            select instrument_key, session_date, label_id, value, label_start_at, label_end_at
            from training_label"""))).all()}
        n = len(hist) - 1
        v, start, end = lab[(W.A, hist[-1], "ret_cc")]
        assert v == ok((100 + n) / (99 + n) - 1)[0]
        assert start == W.ist(2026, 9, 23, 9, 15) and end == W.ist(2026, 9, 23, 15, 30)
        for kind in ("PRE_SESSION", "PRE_OPEN"):                 # strictly after the snapshot
            assert start > (await snap(world, kind, hist[-1])).as_of
        assert lab[(W.A, hist[-1], "ret_oc")][0] == ok((100 + n) / (99.5 + n) - 1)[0]
        assert lab[(W.A, hist[-1], "hit_up_1")][0] == 0.0
        # B's 1:1 bonus goes ex on 09-10: the label is on one basis (not -50%)
        i = hist.index(W.BONUS_EX)
        assert lab[(W.B, W.BONUS_EX, "ret_cc")][0] == ok((100 + i) / (99 + i) - 1)[0]
        assert lab[(W.A, hist[0], "ret_cc")][0] is None              # no previous session
        again = await L.build(world, hist[0], hist[-1], [W.A, W.B])
        assert again["inserted"] == 0 and again["drift_vs_stored"] == 0
