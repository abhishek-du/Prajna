"""label-hold5-v1-asif (E2 labels) and the wf-exp-120-20-20-e5 splits: pure rules on
synthetic inputs, and the builders on the Stage 3 seed world of the TEST database only
(never production)."""

from __future__ import annotations

import datetime as _dt

import pytest
from sqlalchemy import text

from app.training import e2 as X
from app.training import hold as HL
from app.training import splits as SP
from tests.support import stage3_seed as W
from tests.training.test_v3 import CUTOFF, world  # noqa: F401  (fixture)

D0 = _dt.date(2026, 6, 1)


def cal_days(n):
    days, d = [], D0
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d += _dt.timedelta(days=1)
    return days, {d: (_dt.time(9, 15), _dt.time(15, 30)) for d in days}


def bar(d, o, h=None, lo=None, c=None):
    return {"market_date": d, "open": o, "high": h if h is not None else o + 1,
            "low": lo if lo is not None else o - 1, "close": c if c is not None else o,
            "payload_sha256": "p", "factor_applied": None}


def rows_by(rows):
    return {(r["session_date"], r["label_id"]): r for r in rows}


class TestPure:
    def test_definitions_and_explicit_reasons(self):
        days, cal = cal_days(12)
        adj = {d: bar(d, 100.0 + i) for i, d in enumerate(days)}
        del adj[days[7]]                                         # no usable open at T+5 of 2
        adj[days[4]] = bar(days[4], 100, h=90, lo=95)            # malformed T
        r = rows_by(HL.hold_rows("K", days, set(days[:10]), adj, {}, cal))
        assert r[(days[0], "open_adj")]["value"] == 100.0
        assert r[(days[0], "hold5_px")]["value"] == pytest.approx(105 / 100 - 1)
        assert r[(days[0], "hold3_px")]["value"] == pytest.approx(103 / 100 - 1)
        assert r[(days[2], "hold5_px")]["reason"] == "SESSION_MISSING"
        assert {r[(days[4], k)]["reason"] for k in HL.IDS} == {"MALFORMED_BAR"}
        assert r[(days[8], "hold5_px")]["reason"] == "NO_EXIT_SESSION"   # 8 + 5 > 11
        assert r[(days[8], "hold3_px")]["value"] == pytest.approx(111 / 108 - 1)
        assert all(r[k]["value"] is None for k in r if r[k]["status"] != "VALID")
        assert (days[10], "open_adj") not in r                   # not a canon day: no row

    def test_window_counts_calendar_sessions_not_bars(self):
        days, cal = cal_days(8)
        adj = {d: bar(d, 100.0) for d in days if d != days[2]}   # T+2 has no bar
        r = rows_by(HL.hold_rows("K", days, set(days), adj, {}, cal))
        assert r[(days[0], "hold5_px")]["label_end_at"].date() == days[5]
        assert r[(days[0], "hold5_px")]["value"] == pytest.approx(0.0)

    def test_label_window_starts_at_the_open_and_ends_at_the_exit_open(self):
        days, cal = cal_days(8)
        r = rows_by(HL.hold_rows("K", days, {days[0]}, {d: bar(d, 100.0) for d in days},
                                 {}, cal))
        h5 = r[(days[0], "hold5_px")]
        assert h5["label_start_at"].time() == _dt.time(9, 15)
        assert h5["label_end_at"].date() == days[5] and h5["label_end_at"] > h5["label_start_at"]

    def test_total_return_adds_dividend_cash_for_the_holder_of_record_only(self):
        days, cal = cal_days(10)
        adj = {d: bar(d, 100.0) for d in days}
        acts = {days[2]: [{"id": 1, "action_type": "DIVIDEND", "status": None, "factor": None,
                           "amount": 2.0}],
                days[0]: [{"id": 2, "action_type": "DIVIDEND", "status": None, "factor": None,
                           "amount": 9.0}]}                       # ex at T: not in (T, T+h]
        r = rows_by(HL.hold_rows("K", days, set(days), adj, acts, cal))
        assert r[(days[0], "hold5_px")]["value"] == pytest.approx(0.0)
        assert r[(days[0], "hold5_tr")]["value"] == pytest.approx(0.02)
        assert "DIVIDEND_IN_WINDOW" in r[(days[0], "hold5_tr")]["flags"]
        assert r[(days[2], "hold5_tr")]["value"] == pytest.approx(0.0)     # ex = T

    def test_dividend_cash_is_rescaled_by_later_splits_even_after_the_window(self):
        """A 2:1 split (factor 2) after the window, before the cutoff, halves every
        adjusted price of the window; the dividend per share must halve too."""
        days, cal = cal_days(12)
        adj = {d: bar(d, 50.0) for d in days}                    # adjusted basis
        acts = {days[1]: [{"id": 1, "action_type": "DIVIDEND", "status": None,
                           "factor": None, "amount": 2.0}],
                days[11]: [{"id": 2, "action_type": "SPLIT", "status": "EXACT",
                            "factor": 2, "amount": None}]}
        r = rows_by(HL.hold_rows("K", days, set(days[:5]), adj, acts, cal))
        assert r[(days[0], "hold5_tr")]["value"] == pytest.approx(1.0 / 50)
        assert not any(f.startswith("CA_IN_WINDOW") for f in r[(days[0], "hold5_tr")]["flags"])

    def test_dividend_without_amount_is_explicit_and_px_unaffected(self):
        days, cal = cal_days(8)
        acts = {days[1]: [{"id": 1, "action_type": "DIVIDEND", "status": None, "factor": None,
                           "amount": None}]}
        r = rows_by(HL.hold_rows("K", days, {days[0]}, {d: bar(d, 100.0) for d in days},
                                 acts, cal))
        assert r[(days[0], "hold5_tr")]["reason"] == "DIVIDEND_NO_AMOUNT"
        assert r[(days[0], "hold5_px")]["value"] == pytest.approx(0.0)

    def test_split_inside_the_window_is_flagged_never_a_crash(self):
        days, cal = cal_days(8)
        adj = {d: bar(d, 50.0 + i) for i, d in enumerate(days)}   # already adjusted
        acts = {days[2]: [{"id": 7, "action_type": "SPLIT", "status": "EXACT", "factor": 2,
                           "amount": None}],
                days[3]: [{"id": 8, "action_type": "RIGHTS", "status": None, "factor": None,
                           "amount": None}]}
        r = rows_by(HL.hold_rows("K", days, {days[0]}, adj, acts, cal))
        assert r[(days[0], "hold5_px")]["value"] == pytest.approx(55 / 50 - 1)
        assert r[(days[0], "hold5_px")]["flags"] == ["CA_IN_WINDOW:7",
                                                     "UNSUPPORTED_CA_IN_WINDOW:RIGHTS"]

    def test_rows_are_deterministic(self):
        days, cal = cal_days(10)
        adj = {d: bar(d, 100.0 + i) for i, d in enumerate(days)}
        a = HL.hold_rows("K", days, set(days), adj, {}, cal)
        b = HL.hold_rows("K", days, set(days), adj, {}, cal)
        assert a == b and HL.L._digest(a) == HL.L._digest(b)


class TestSplitsE5:
    def test_e5_blocks_equal_make_folds_and_e1_is_unchanged(self):
        days, _ = cal_days(257)
        blocks = SP.folds(days, **SP.SCHEMES[SP.SCHEME_E5])
        idx = {d: i for i, d in enumerate(days)}
        got = {}
        for b in blocks:
            got.setdefault(b["fold"], {})[b["role"].lower()] = range(
                idx[b["session_from"]], idx[b["session_to"]] + 1)
        assert got == dict(enumerate(X.make_folds(257)))
        assert not SP.violations(days, blocks)
        assert all(b["embargo_sessions"] == 5 for b in blocks)
        e1 = SP.folds(days)                                     # the stored E1 scheme
        assert len(e1) == 15 and all(b["embargo_sessions"] == 1 for b in e1)
        assert e1 == SP.folds(days, **SP.SCHEMES[SP.SCHEME])

    def test_the_tail_purge_keeps_every_test_exit_inside_the_data(self):
        days, _ = cal_days(170)                    # 150 + 20 = TEST end; +5 needed
        assert not SP.folds(days, **SP.SCHEMES[SP.SCHEME_E5])
        days, _ = cal_days(175)
        assert len(SP.folds(days, **SP.SCHEMES[SP.SCHEME_E5])) == 3


@pytest.mark.db
@pytest.mark.integration
@pytest.mark.isolation("REPEATABLE READ")
class TestBuildersOnTheTestDatabase:
    async def _rows(self, s):
        return {(r[0], r[1], r[2]): (r[3], r[4], r[5], r[6]) for r in (await s.execute(text("""
            select instrument_key, session_date, label_id, value, status, reason, flags
            from training_label where label_version = :v"""), {"v": HL.VERSION})).all()}

    async def test_values_bonus_basis_and_refusals(self, world):  # noqa: F811
        hist = W.history()
        rep = await HL.build(world, hist[0], hist[-1], cutoff=CUTOFF, keys=[W.A, W.B, W.E])
        assert rep["drift_vs_stored"] == 0 and rep["inserted"] == rep["rows"]
        lab = await self._rows(world)
        assert lab[(W.A, hist[0], "hold5_px")][0] == pytest.approx(104.5 / 99.5 - 1)
        i = hist.index(W.BONUS_EX) - 2                       # B: the 1:1 bonus inside (T, T+5]
        v, st, _, flags = lab[(W.B, hist[i], "hold5_px")]
        assert st == "VALID" and v == pytest.approx((100 + i + 5 - 0.5) / (100 + i - 0.25) - 1)
        assert any(f.startswith("CA_IN_WINDOW:") for f in flags)
        assert lab[(W.E, _dt.date(2026, 9, 1), "open_adj")][1:3] == ("MISSING_INPUT",
                                                                    "BAR_REFUSED")
        assert lab[(W.A, hist[-1], "hold5_px")][1] == "MISSING_INPUT"   # no exit bar yet

    async def test_deterministic_idempotent_and_append_only(self, world):  # noqa: F811
        hist = W.history()
        a = await HL.build(world, hist[-15], hist[-1], cutoff=CUTOFF, keys=[W.A, W.B])
        b = await HL.build(world, hist[-15], hist[-1], cutoff=CUTOFF, keys=[W.A, W.B])
        assert a["rows_sha256"] == b["rows_sha256"] and b["inserted"] == 0
        assert b["drift_vs_stored"] == 0 and a["source_fingerprints"] == b["source_fingerprints"]

    async def test_labels_start_after_every_snapshot(self, world):  # noqa: F811
        from app.features import snapshots as SN
        hist = W.history()
        await HL.build(world, hist[-1], hist[-1], cutoff=CUTOFF, keys=[W.A])
        start = (await world.execute(text("""select min(label_start_at) from training_label
            where label_version = :v and session_date = :d"""),
            {"v": HL.VERSION, "d": hist[-1]})).scalar()
        assert start > (await SN.resolve(world, hist[-1], "PRE_SESSION")).as_of

    async def test_e5_splits_refuse_other_labels(self, world):  # noqa: F811
        with pytest.raises(ValueError, match="does not use scheme"):
            await SP.build(world, "stage4-ds-v3-asif", "label-v2", scheme=SP.SCHEME_E5)
        with pytest.raises(ValueError, match="does not use scheme"):
            await SP.build(world, "stage4-ds-v3-asif", HL.VERSION)
