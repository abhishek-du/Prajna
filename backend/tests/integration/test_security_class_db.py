"""The classification run on a real (test) database (phase 3)."""

from __future__ import annotations

import json
import os

import pytest
from sqlalchemy import text

from app.core import clock
from app.ingest.security_class import classify_securities
from tests.support import stage2_seed as SEED
from tests.support.stage2_seed import NOW, SPX, H, N, R

pytestmark = [pytest.mark.db, pytest.mark.integration]
TOKEN = os.environ["PRAJNA_WRITE_TOKEN"]


async def _classes(s):
    return {r.instrument_key: (r.security_class, r.subclass, r.status) for r in (await s.execute(
        text("select * from instrument_security_class"))).all()}


async def test_classify_idempotent_and_review_is_reported(db_session):
    s = db_session
    clock.freeze(NOW)
    try:
        await SEED.seed(s)
        rep = await classify_securities(s, commit=True, token=TOKEN)
        got = await _classes(s)
        assert got[R] == ("STOCK", None, "CLASSIFIED")          # ISIN + profile sector
        assert got[H] == (None, None, "UNCLASSIFIED")           # no fundamentals yet
        assert got[N] == ("OTHER", "INDEX", "CLASSIFIED")
        assert got[SPX] == ("OTHER", "GLOBAL", "CLASSIFIED")
        signals = (await s.execute(text("select signals from instrument_security_class "
                                        "where instrument_key=:k"), {"k": R})).scalar()
        assert signals["isin"]["vote"] == "COMPANY"
        assert signals["financials"]["vote"] == "FINANCIALS"

        again = await classify_securities(s, commit=True, token=TOKEN)
        assert again["changed"] == 0 and again["counts"] == rep["counts"]

        # HDFCBANK's vendor profile arrives WITHOUT any financials: company ISIN
        # vs no financials is a contradiction -> REVIEW, reported, never silent
        fr = await SEED._run(s, "facts2", source="UPSTOX_REST_V2")
        sha = await SEED._payload(s, fr, "UPSTOX_REST_V2")
        await s.execute(text("""
            insert into fundamental_snapshot (instrument_key, isin, statement_type, payload,
              source, run_id, payload_sha256, fetched_at, knowable_at, knowable_at_verified,
              knowable_at_basis) values (:k, 'INE040A01034', 'profile', cast(:p as jsonb),
              'UPSTOX_REST_V2', :r, :h, :t, :t, false, 'fetched')"""),
            {"k": H, "p": json.dumps({"sector": None}), "r": fr, "h": sha, "t": NOW})
        third = await classify_securities(s, commit=True, token=TOKEN)
        assert (await _classes(s))[H] == (None, None, "REVIEW")
        assert third["review"] == [H] and third["changed"] == 1
        n = (await s.execute(text("""select count(*) from ingest_anomaly a join ingest_run r
            using (run_id) where r.run_id = cast(:r as uuid) and a.subject = 'security_class'"""),
            {"r": third["run_id"]})).scalar()
        assert n == 2                                         # REVIEW + changed
    finally:
        clock.unfreeze()


async def test_new_listing_grace_for_review_without_financials(db_session):
    """Decision D-NEW-LISTING-GRACE (2026-10-08): a NEW listing in REVIEW only because
    the vendor has no financials yet is in the 7-day grace; after 7 days, or with any
    other disagreeing signal, it counts against D again."""
    import datetime as _dt

    from app.acceptance.stage1 import review_in_new_listing_grace
    s = db_session
    clock.freeze(NOW)
    try:
        await SEED.seed(s)
        fr = await SEED._run(s, "facts2", source="UPSTOX_REST_V2")
        sha = await SEED._payload(s, fr, "UPSTOX_REST_V2")
        await s.execute(text("""
            insert into fundamental_snapshot (instrument_key, isin, statement_type, payload,
              source, run_id, payload_sha256, fetched_at, knowable_at, knowable_at_verified,
              knowable_at_basis) values (:k, 'INE040A01034', 'profile', cast(:p as jsonb),
              'UPSTOX_REST_V2', :r, :h, :t, :t, false, 'fetched')"""),
            {"k": H, "p": json.dumps({"sector": None}), "r": fr, "h": sha, "t": NOW})
        await classify_securities(s, commit=True, token=TOKEN)
        assert (await _classes(s))[H] == (None, None, "REVIEW")
        today = NOW.date()
        grace = today - _dt.timedelta(days=7)

        async def first_seen(d):
            await s.execute(text("update instrument set first_seen = :d where "
                                 "instrument_key = :k and valid_to = 'infinity'"), {"d": d, "k": H})
        await first_seen(today - _dt.timedelta(days=2))            # a new listing
        assert await review_in_new_listing_grace(s, grace) == 1
        await first_seen(today - _dt.timedelta(days=8))            # past the grace
        assert await review_in_new_listing_grace(s, grace) == 0
        await first_seen(today - _dt.timedelta(days=2))
        await s.execute(text("""update instrument_security_class set signals =
            jsonb_set(signals, '{name,vote}', '"FUND_UNIT"') where instrument_key = :k"""),
            {"k": H})                                                # another disagreement
        assert await review_in_new_listing_grace(s, grace) == 0
    finally:
        clock.unfreeze()
