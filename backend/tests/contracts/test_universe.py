"""Pre-open eligibility and the subscription cap. Pure; no database."""

from __future__ import annotations

import random
from typing import ClassVar

import pytest

from app.contracts import universe as U
from app.contracts.provenance import AnomalyKind, AnomalySeverity
from app.contracts.universe import (
    RULE_SELECTED,
    MasterInstrument,
    classify,
    plan_subscription,
    rules_sha256,
    select_preopen,
)
from app.ingest.checks import CheckResult, check_universe_cap
from tests.support import upstox_master as M


def _inst(r: dict) -> MasterInstrument:
    return MasterInstrument(r["instrument_key"], r["segment"], r.get("instrument_type"),
                            r.get("isin"), r.get("trading_symbol"))


ALL = [_inst(r) for r in M.ALL]


class TestIsinIsNotTheRule:
    @pytest.mark.parametrize("r", [M.RELIANCE, M.NIFTYBEES, M.IN9_EQ],
                             ids=["INE", "INF-etf", "IN9"])
    def test_every_isin_prefix_is_eligible_when_the_series_is(self, r):
        assert classify(_inst(r)) == RULE_SELECTED

    def test_missing_isin_does_not_matter(self):
        assert classify(MasterInstrument("NSE_EQ|X1", "NSE_EQ", "EQ", None)) == RULE_SELECTED

    def test_an_ine_isin_does_not_rescue_a_debt_series(self):
        assert M.DEBT["isin"].startswith("INE")
        assert classify(_inst(M.DEBT)) == "excluded:series=N0"


class TestNonEquity:
    @pytest.mark.parametrize("r, rule", [
        (M.GSEC, "excluded:series=SG"),
        (M.DEBT, "excluded:series=N0"),
        (M.TBILL, "excluded:series=TB"),
        (M.GOLDB, "excluded:series=GB"),
        (M.NO_SERIES, "excluded:series=<none>"),
        (M.INDEX, "excluded:segment=NSE_INDEX"),
        (M.FUT, "excluded:segment=NSE_FO"),
    ])
    def test_excluded_under_a_named_rule(self, r, rule):
        assert classify(_inst(r)) == rule

    def test_bse_is_excluded_by_segment(self):
        bse = MasterInstrument("BSE_EQ|INE002A01018", "BSE_EQ", "A", "INE002A01018")
        assert classify(bse) == "excluded:segment=BSE_EQ"

    @pytest.mark.parametrize("series", sorted(U.TRADEABLE_EQUITY_SERIES))
    def test_every_tradeable_series_is_selected(self, series):
        assert classify(MasterInstrument("NSE_EQ|K", "NSE_EQ", series)) == RULE_SELECTED


class TestSelection:
    def test_every_instrument_is_accounted_for(self):
        sel = select_preopen(ALL)
        assert sum(sel.counts().values()) == len(ALL)
        assert len(sel.members) == len(M.ELIGIBLE)
        excluded = {k for keys in sel.excluded.values() for k in keys}
        assert excluded | set(sel.members) == {i.instrument_key for i in ALL}

    def test_order_is_canonical_whatever_the_input_order(self):
        base = select_preopen(ALL)
        assert list(base.members) == sorted(base.members)
        for seed in range(5):
            shuffled = ALL[:]
            random.Random(seed).shuffle(shuffled)
            s = select_preopen(shuffled)
            assert s.members == base.members and s.members_sha256 == base.members_sha256
            assert s.excluded == base.excluded

    def test_repeated_runs_are_identical(self):
        assert select_preopen(ALL) == select_preopen(ALL)

    def test_series_is_carried_for_each_member(self):
        sel = select_preopen(ALL)
        assert sel.series_of[M.SME["instrument_key"]] == "SM"


class TestRulesFingerprint:
    def test_stable(self):
        assert rules_sha256() == rules_sha256()
        assert U.rules_fingerprint()["isin_prefix_rule"] is None

    def test_changes_when_the_rule_set_changes(self, monkeypatch):
        before = rules_sha256()
        monkeypatch.setattr(U, "TRADEABLE_EQUITY_SERIES", frozenset({"EQ"}))
        assert rules_sha256() != before


class TestCap:
    KEYS: ClassVar[list[str]] = [f"NSE_EQ|INE00000{i:04d}" for i in range(10)]

    def test_no_cap_keeps_everything(self):
        p = plan_subscription(self.KEYS, None)
        assert p.subscribed == tuple(self.KEYS) and p.excluded == ()

    @pytest.mark.parametrize("cap", [10, 11, 5000])
    def test_cap_at_or_above_size_excludes_nothing(self, cap):
        assert plan_subscription(self.KEYS, cap).excluded == ()

    def test_cap_cuts_the_sorted_tail_by_name(self):
        shuffled = self.KEYS[::-1]
        p = plan_subscription(shuffled, 7)
        assert p.subscribed == tuple(self.KEYS[:7])
        assert p.excluded == tuple(self.KEYS[7:])
        assert p.cap == 7

    @pytest.mark.parametrize("cap", [0, -1])
    def test_nonsense_cap_is_refused(self, cap):
        with pytest.raises(ValueError):
            plan_subscription(self.KEYS, cap)

    def test_check_names_every_dropped_key_and_marks_the_cap_unverified(self):
        res = CheckResult()
        kept = check_universe_cap(res, requested=self.KEYS[::-1], cap=4, stream="t")
        assert kept == self.KEYS[:4]
        (a,) = res.anomalies
        assert (a.severity, a.kind) == (AnomalySeverity.WARN, AnomalyKind.COVERAGE_CAP)
        assert a.detail["dropped_keys"] == self.KEYS[4:] and "B5" in a.detail["basis"]

    def test_check_is_silent_under_the_cap(self):
        res = CheckResult()
        check_universe_cap(res, requested=self.KEYS, cap=None, stream="t")
        assert res.anomalies == []
