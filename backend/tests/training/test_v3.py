"""Stage 4 builder v3 on the Stage 3 seed world (tests/support/stage3_seed.py):
the build contract (frozen versions, registry pinning, one hash per version),
label-v2 (definitions, corporate-action basis as observed at the cutoff, explicit
validity rows and flags, determinism), samples (eligibility, masks, exclusions)
and walk-forward splits (chronology, embargo). Test database only; no network."""

from __future__ import annotations

import dataclasses
import datetime as _dt
import os
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.canon import process as CP
from app.core import clock
from app.features import snapshots as SN
from app.features.compute import ok
from app.training import labels as L
from app.training import policy as P
from app.training import replay as RP
from app.training import samples as SM
from app.training import splits as SP
from tests.support import stage3_seed as W
from tests.support.stage2_seed import _payload, _run

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.isolation("REPEATABLE READ")]
TOKEN = os.environ["PRAJNA_WRITE_TOKEN"]
STRICT = P.DATASETS["strict"]
CUTOFF = W.NOW                                    # 2026-09-24 12:00 IST


@pytest.fixture
async def world(db_session):
    clock.freeze(W.NOW)
    ids = await W.seed(db_session)
    await CP.process(db_session, commit=True, token=TOKEN)
    db_session.info["ids"] = ids
    yield db_session
    clock.unfreeze()


def _labels(s):
    async def go(version=L.VERSION2):
        return {(r[0], r[1], r[2]): (r[3], r[4], r[5], r[6]) for r in (await s.execute(text("""
            select instrument_key, session_date, label_id, value, status, reason, flags
            from training_label where label_version = :v"""), {"v": version})).all()}
    return go


async def _split(s, key, ex, fetched, factor=2):
    """A SPLIT for `key` with ex-date `ex`, announced long before, STORED at `fetched`."""
    rid = await _run(s, f"ca.{uuid.uuid4().hex[:6]}", source="UPSTOX_REST_V2")
    sha = await _payload(s, rid, "UPSTOX_REST_V2")
    ca = (await s.execute(text("""insert into corporate_action (isin, instrument_key,
        trading_symbol, action_type, ex_date, announcement_date, content_sha256, vendor_payload,
        source, run_id, payload_sha256, fetched_at, knowable_at, knowable_at_verified,
        knowable_at_basis) values (:isin, :k, 'X', 'SPLIT', :x, '2026-08-01', :c, '{}',
        'UPSTOX_REST_V2', :r, :h, :f, :kn, false, 'KN-CA') returning id"""),
        {"isin": key.split("|")[1], "k": key, "x": ex, "c": uuid.uuid4().hex * 2, "r": rid,
         "h": sha, "f": fetched, "kn": W.ist(2026, 8, 1, 23, 59, 59)})).scalar()
    await s.execute(text("""insert into ca_factor (ca_id, instrument_key, action_type, ex_date,
        status, method, factor_price, factor_volume, knowable_at, vendor_applied, reason,
        method_version, derived_at, run_id) values (:c, :k, 'SPLIT', :x, 'EXACT', 'FACE_VALUE',
        :f, :f, :kn, 'NOT_APPLIED', 'test', 'cafactor-v1', now(), :r)"""),
        {"c": ca, "k": key, "x": ex, "f": factor, "kn": W.ist(2026, 8, 1, 23, 59, 59), "r": rid})
    await s.commit()
    return ca


# ── the build contract ─────────────────────────────────────────────────────────────
class TestBuildContract:
    async def test_frozen_versions_are_refused(self, world):
        for v in ("stage4-ds-v1-strict", "stage4-ds-v2-strict", "stage4-ds-v2-asif"):
            with pytest.raises(RP.BuildContractError, match="frozen"):
                await RP.check_contract(world, dataclasses.replace(STRICT, version=v))
        with pytest.raises(L.FrozenLabelVersion):
            await L.build(world, _dt.date(2026, 9, 1), _dt.date(2026, 9, 2))

    async def test_registry_is_pinned_per_version(self, world):
        with pytest.raises(RP.BuildContractError, match="must be built with"):
            await RP.check_contract(world, dataclasses.replace(STRICT,
                                                               registry_version="features-v3"))
        await world.execute(text("""insert into training_dataset_run (run_id, dataset_version,
            knowability_policy, policy_params, registry_version, registry_sha256, feature_count,
            start_date, end_date, snapshots, status, operator, started_at) values (:r, :v,
            'STRICT_PIT-v2', '{}', 'features-v4', :h, 104, '2026-09-01', '2026-09-01',
            '{PRE_SESSION}', 'COMPLETE', 'test', now())"""),
            {"r": uuid.uuid4(), "v": STRICT.version, "h": "0" * 64})
        await world.commit()
        with pytest.raises(RP.BuildContractError, match="already holds rows of registry"):
            await RP.open_run(world, STRICT, _dt.date(2026, 9, 1), _dt.date(2026, 9, 1), None,
                              "test")

    async def test_run_records_code_and_contract(self, world):
        rid = await RP.open_run(world, STRICT, _dt.date(2026, 9, 23), _dt.date(2026, 9, 23),
                                None, "test", code={"git_sha": "abc", "dirty": False})
        r = (await world.execute(text("""select code_git_sha, build_contract, registry_version
            from training_dataset_run where run_id = :r"""), {"r": rid})).one()
        assert r[0] == "abc" and r[2] == "features-v5"          # builder v4 (2026-10-21)
        assert r[1]["search_path"] == "train_strict, public" and r[1]["code_dirty"] is False

    async def test_strict_shadow_equals_the_production_views(self, world):
        await _split(world, W.C, _dt.date(2026, 9, 15), W.ist(2026, 9, 24, 13))
        for view in ("canon_corporate_action", "canon_ca_factor"):
            pub = (await world.execute(text(f"select id, knowable_at from public.{view} "  # noqa: S608
                                            "order by id"))).all()
            shadow = (await world.execute(text(f"select id, knowable_at from train_strict.{view} "  # noqa: S608
                                               "order by id"))).all()
            assert pub == shadow and pub


# ── label-v2 ────────────────────────────────────────────────────────────────────────
class TestLabelV2:
    async def test_definitions_basis_and_timing(self, world):
        hist = W.history()
        rep = await L.build_v2(world, hist[0], hist[-1], cutoff=CUTOFF, keys=[W.A, W.B])
        assert rep["drift_vs_stored"] == 0 and rep["inserted"] == rep["rows"]
        lab = await _labels(world)()
        n = len(hist) - 1
        assert lab[(W.A, hist[-1], "ret_cc")][:2] == (ok((100 + n) / (99 + n) - 1)[0], "VALID")
        i = hist.index(W.BONUS_EX)                 # B's 1:1 bonus: T-1 adjusted, flagged
        v, st, why, flags = lab[(W.B, W.BONUS_EX, "ret_cc")]
        assert v == ok((100 + i) / (99 + i) - 1)[0] and any(f.startswith("CA_EX_T:") and
                                                           f.endswith(":2") for f in flags)
        assert lab[(W.A, hist[0], "ret_cc")][1:3] == ("MISSING_INPUT", "PREV_SESSION_MISSING")
        start = (await world.execute(text("""select label_start_at from training_label
            where label_version = 'label-v2' and session_date = :d limit 1"""),
            {"d": hist[-1]})).scalar()
        for kind in ("PRE_SESSION", "PRE_OPEN"):
            assert start > (await SN.resolve(world, hist[-1], kind)).as_of

    async def test_an_action_counts_only_once_observed_before_the_cutoff(self, world):
        """C 'splits' 1:2 on 09-15 (the seed's prices do not move): stored at 13:00, after
        the noon cutoff -> not applied, no flag; a later cutoff applies it (T-1 / 2)."""
        d = _dt.date(2026, 9, 15)
        await _split(world, W.C, d, W.ist(2026, 9, 24, 13))
        await L.build_v2(world, d, d, cutoff=CUTOFF, keys=[W.C])
        v, _, _, flags = (await _labels(world)())[(W.C, d, "ret_cc")]
        i = W.history().index(d)
        assert v == ok((50 + 0.5 * i) / (50 + 0.5 * (i - 1)) - 1)[0] and flags == []
        # a cutoff after the fetch applies it: the recompute differs from the stored rows on
        # every label of (T, C) (flags) - reported as drift, never overwritten
        later = await L.build_v2(world, d, d, cutoff=W.ist(2026, 9, 24, 14), keys=[W.C])
        assert later["inserted"] == 0 and later["drift_vs_stored"] == len(L.LABELS)
        assert (await _labels(world)())[(W.C, d, "ret_cc")][0] == v

    async def test_a_later_action_never_changes_an_earlier_label(self, world):
        hist = W.history()
        t = hist[-2]
        await L.build_v2(world, t, t, cutoff=CUTOFF, keys=[W.A])
        before = (await _labels(world)())[(W.A, t, "ret_cc")]
        await _split(world, W.A, hist[-1], W.ist(2026, 9, 24, 9))   # ex the NEXT session
        clock.freeze(W.ist(2026, 9, 24, 12, 30))
        rep = await L.build_v2(world, t, t, cutoff=W.ist(2026, 9, 24, 12, 30), keys=[W.A])
        assert rep["drift_vs_stored"] == 0                      # same values, same flags
        assert (await _labels(world)())[(W.A, t, "ret_cc")] == before

    async def test_refused_bars_get_explicit_rows(self, world):
        """E's vendor-adjusted bars before the horizon (09-10) are LOW-confidence refused:
        label-v2 records BAR_REFUSED rows instead of omitting them (label-v1 did)."""
        d = _dt.date(2026, 9, 1)
        await L.build_v2(world, d, d, cutoff=CUTOFF, keys=[W.E])
        lab = await _labels(world)()
        assert {lab[(W.E, d, k)][1:3] for k in L.LABELS} == {("MISSING_INPUT", "BAR_REFUSED")}

    async def test_deterministic_and_idempotent(self, world):
        hist = W.history()
        a = await L.build_v2(world, hist[-10], hist[-1], cutoff=CUTOFF, keys=[W.A, W.B, W.E])
        b = await L.build_v2(world, hist[-10], hist[-1], cutoff=CUTOFF, keys=[W.A, W.B, W.E])
        assert a["rows_sha256"] == b["rows_sha256"] and b["inserted"] == 0
        assert b["drift_vs_stored"] == 0 and a["source_fingerprints"] == b["source_fingerprints"]
        runs = (await world.execute(text("""select count(*), count(distinct rows_sha256)
            from training_label_run"""))).one()
        assert tuple(runs) == (2, 1)

    def test_pure_validity_rules(self):
        d0, d1 = _dt.date(2026, 9, 1), _dt.date(2026, 9, 2)
        cal = {d0: (_dt.time(9, 15), _dt.time(15, 30)), d1: (_dt.time(9, 15), _dt.time(15, 30))}
        prev = {d1: d0, d0: None}

        def bar(d, o, h, lo, c):
            return {"market_date": d, "open": Decimal(o), "high": Decimal(h), "low": Decimal(lo),
                    "close": Decimal(c), "payload_sha256": "p", "factor_applied": 1}
        good = bar(d0, 100, 101, 99, 100)
        rows = L.v2_rows("K", [d1], {d0: good, d1: bar(d1, 100, 99, 101, 100)}, {}, cal, prev)
        assert {r["reason"] for r in rows} == {"MALFORMED_BAR"}
        rows = L.v2_rows("K", [d1], {d1: bar(d1, 100, 103, 97, 101)}, {}, cal, prev)
        by = {r["label_id"]: r for r in rows}
        assert by["ret_cc"]["reason"] == "PREV_SESSION_MISSING" and by["ret_oc"]["value"]
        assert set(by["ret_cc"]["flags"]) == {"AMBIGUOUS_ORDER_1", "AMBIGUOUS_ORDER_2"}
        rows = L.v2_rows("K", [d1], {d0: good, d1: bar(d1, 140, 141, 139, 140)}, {}, cal, prev)
        assert "EXTREME_UNEXPLAINED" in rows[0]["flags"]
        rows = L.v2_rows("K", [d1], {d0: good, d1: bar(d1, 140, 141, 139, 140)},
                         {d1: [{"id": 7, "action_type": "RIGHTS", "status": "UNSUPPORTED",
                                "factor": None}]}, cal, prev)
        assert {"EXTREME_UNEXPLAINED", "UNSUPPORTED_CA_EX_T:RIGHTS"} <= set(rows[0]["flags"])
        rows = L.v2_rows("K", [d1], {d0: good}, {}, cal, prev)
        assert {r["reason"] for r in rows} == {"BAR_REFUSED"}


# ── samples ─────────────────────────────────────────────────────────────────────────
class TestSamples:
    async def test_eligibility_masks_and_exclusions(self, world):
        hist = W.history()
        days = [hist[hist.index(W.BONUS_EX) + 1], hist[-1]]     # 09-11 (B: ex + 1) and 09-23
        rid = await RP.open_run(world, STRICT, days[0], days[-1], None, "test",
                                code={"git_sha": "t", "dirty": False})
        for d in days:
            await RP.replay_snapshot(world, STRICT, await SN.resolve(world, d, "PRE_SESSION"), rid)
        await L.build_v2(world, days[0], days[-1], cutoff=CUTOFF,
                         keys=[W.A, W.B, W.C, W.DD, W.E])
        rep = await SM.build(world, STRICT.version, L.VERSION2)
        assert rep["inserted"] == rep["samples"] == 2 * 5
        sm = {(r[0], r[1]): r[2:] for r in (await world.execute(text("""select instrument_key,
            session_date, eligible, exclusion_reasons, masks, core_valid, labels_valid
            from training_sample"""))).all()}
        assert sm[(W.B, days[0])][2] == ["CA_WINDOW"] and sm[(W.A, days[0])][2] == []
        assert "LABEL_BAR_REFUSED" in sm[(W.E, days[0])][1] or \
            "CORE_FEATURE_NOT_VALID" in sm[(W.E, days[0])][1]
        assert sm[(W.A, days[-1])][0] is True and sm[(W.A, days[-1])][3] == 24
        again = await SM.build(world, STRICT.version, L.VERSION2)
        assert again["inserted"] == 0 and again["build_sha256"] == rep["build_sha256"]

    def test_pure_sample_rules(self):
        d = _dt.date(2026, 9, 2)
        at = W.ist(2026, 9, 2, 8, 59, 59)
        core = dict.fromkeys(SM.CORE_INSTRUMENT, "VALID")
        lab = [{"label_id": k, "status": "VALID", "reason": None, "flags": [],
                "label_start_at": W.ist(2026, 9, 2, 9, 15)} for k in L.LABELS]
        r = SM.sample_row("x", "l", d, "PRE_SESSION", at, "K", core, lab, False)
        assert r["eligible"] and r["exclusion_reasons"] == [] and r["core_valid"] == 24
        r = SM.sample_row("x", "l", d, "PRE_SESSION", at, "K", {**core, "rsi_14": "STALE_INPUT"},
                          None, True)
        assert r["exclusion_reasons"] == ["CORE_FEATURE_NOT_VALID", "NO_LABEL"]
        assert r["core_not_valid"] == ["rsi_14"] and r["masks"] == ["CA_WINDOW"]


# ── splits ──────────────────────────────────────────────────────────────────────────
class TestSplits:
    def test_chronological_embargoed_and_non_overlapping(self):
        ss = [_dt.date(2025, 1, 1) + _dt.timedelta(days=i) for i in range(256)]
        fs = SP.folds(ss)
        assert len(fs) == 15                                  # 5 folds x 3 roles
        pos = {d: i for i, d in enumerate(ss)}
        for k in range(5):
            tr, va, te = (next(f for f in fs if f["fold"] == k and f["role"] == r)
                          for r in ("TRAIN", "VALID", "TEST"))
            assert pos[va["session_from"]] - pos[tr["session_to"]] == 2     # 1 embargo session
            assert pos[te["session_from"]] - pos[va["session_to"]] == 2
            assert tr["session_from"] == ss[0] and tr["sessions"] == 120 + 20 * k
            assert va["sessions"] == te["sessions"] == 20

    def test_too_few_sessions_gives_no_fold(self):
        ss = [_dt.date(2026, 9, 24) + _dt.timedelta(days=i) for i in range(10)]
        assert SP.folds(ss) == []


# ── gap closure (2026-10-12): guards, split verification, integrity, recovery ───────
class TestGapClosure:
    async def test_samples_and_splits_refuse_frozen_versions(self, world):
        for ds, lv in (("stage4-ds-v2-asif", L.VERSION2), (STRICT.version, L.VERSION)):
            with pytest.raises(RP.BuildContractError, match="frozen"):
                await SM.build(world, ds, lv)
            with pytest.raises(RP.BuildContractError, match="frozen"):
                await SP.build(world, ds, lv)

    def test_split_violations_catch_overlap_and_embargo(self):
        ss = [_dt.date(2025, 1, 1) + _dt.timedelta(days=i) for i in range(256)]
        good = SP.folds(ss)
        assert SP.violations(ss, good) == []
        bad = [dict(b) for b in good]
        va = next(b for b in bad if b["fold"] == 0 and b["role"] == "VALID")
        va["session_from"] = next(b for b in bad if b["fold"] == 0 and b["role"] == "TRAIN"
                                  )["session_to"]                      # overlaps TRAIN
        v = SP.violations(ss, bad)
        assert any("embargo" in x for x in v) and any("declared" in x for x in v)
        assert SP.violations(ss, [b for b in good if b["role"] != "TEST"])

    async def test_integrity_checks_pass_on_a_build_and_catch_a_bad_flag(self, world):
        hist = W.history()
        d = hist[-1]
        rid = await RP.open_run(world, STRICT, d, d, None, "test",
                                code={"git_sha": "t", "dirty": False})
        await RP.replay_snapshot(world, STRICT, await SN.resolve(world, d, "PRE_SESSION"), rid)
        await L.build_v2(world, hist[-3], d, cutoff=CUTOFF, keys=[W.A, W.B, W.C, W.DD, W.E])
        await SM.build(world, STRICT.version, L.VERSION2)
        from app.training import integrity as IG
        assert (await IG.label_checks(world, L.VERSION2))["pass"]
        assert (await IG.sample_checks(world, STRICT.version, L.VERSION2))["pass"]
        # a label row flagged AMBIGUOUS although its thresholds were not both touched
        for lid, v in (("hit_up_1", 1.0), ("hit_dn_1", 0.0)):
            await world.execute(text("""insert into training_label (label_version, session_date,
                instrument_key, label_id, value, status, label_start_at, label_end_at,
                inputs_sha256, computed_at, flags) values ('label-x', :d, 'K', :l, :v, 'VALID',
                :a, :b, :h, now(), '{AMBIGUOUS_ORDER_1}')"""),
                {"d": d, "l": lid, "v": v, "a": W.ist(2026, 9, 23, 9, 15),
                 "b": W.ist(2026, 9, 23, 15, 30), "h": "0" * 64})
        bad = await IG.label_checks(world, "label-x")
        assert bad["violations"]["ambiguous_flag"] == 1 and not bad["pass"]

    async def test_stale_runs_are_reported_then_reaped_keeping_done_snapshots(self, world):
        d = W.history()[-1]
        rid = await RP.open_run(world, STRICT, d, d, None, "test",
                                code={"git_sha": "t", "dirty": False})
        await RP.replay_snapshot(world, STRICT, await SN.resolve(world, d, "PRE_SESSION"), rid)
        clock.freeze(W.NOW + _dt.timedelta(hours=13))          # the worker never finished
        stale = await RP.stale_runs(world, _dt.timedelta(hours=12))
        assert [r["run_id"] for r in stale] == [str(rid)] and stale[0]["snapshots_done"] == 1
        await RP.reap_runs(world, _dt.timedelta(hours=12))
        st = (await world.execute(text("""select status, error, sessions_done from
            training_dataset_run where run_id = :r"""), {"r": rid})).one()
        assert st[0] == "FAILED" and st[1].startswith("reaped") and st[2] == 1
        assert await RP.stale_runs(world, _dt.timedelta(hours=12)) == []
        c = await RP.completeness(world, STRICT, d, d)
        assert c["done"] == 1 and c["expected"] == 2 and c["missing"] == [f"{d} PRE_OPEN"]
