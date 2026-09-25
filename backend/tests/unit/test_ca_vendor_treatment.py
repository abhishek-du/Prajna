"""Which corporate actions the vendor applied to our stored history (phase 7),
on the measured real events."""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal as D

import pytest

from app.ingest.ca_derive import vendor_treatment

LATE = _dt.date(2026, 9, 23)              # the 2020+ history was fetched on 2026-09-23


@pytest.mark.parametrize("sym,f,prev,ex_open,ex,expect", [
    ("LICI", D(2), D("415.0"), D("417.6"), _dt.date(2026, 5, 29), "APPLIED"),
    ("TRENT", D("1.5"), D("2838.5"), D("2830.0"), _dt.date(2026, 6, 4), "APPLIED"),
    ("IDEALTECHO", D(2), D("171.0"), D("95.0"), _dt.date(2026, 9, 11), "NOT_APPLIED"),
    ("DHARIWAL", D(5), D("386.0"), D("78.7"), _dt.date(2026, 2, 6), "NOT_APPLIED"),
    ("JAKHARIA", D(3), D("173.6"), D("60.7"), _dt.date(2025, 10, 8), "NOT_APPLIED"),
    ("UEL", D(3), D("371.35"), D("117.65"), _dt.date(2025, 10, 10), "NOT_APPLIED"),
])
def test_measured_real_events(sym, f, prev, ex_open, ex, expect):
    assert vendor_treatment(f, prev, ex_open, LATE, ex)[0] == expect, sym


def test_bars_fetched_before_the_ex_date_say_nothing_about_the_vendor():
    # CHAVDA before 2026-09-25: 740 raw bars fetched 09-23, bonus ex 09-24 - raw by
    # construction (basis_as_of), but no evidence yet of the vendor's post-ex treatment
    v, ev = vendor_treatment(D(2), D("140.0"), None, _dt.date(2026, 9, 23),
                             _dt.date(2026, 9, 24))
    assert v == "UNKNOWN" and "not observed yet" in ev["why"]


def test_ca_adjustment_observations_prove_the_vendor_applied_it():
    # CHAVDA after the 2026-09-25 re-fetch: 4 (live) / 740 (replay) explained revisions
    v, ev = vendor_treatment(D(2), D("140.0"), D("74.0"), _dt.date(2026, 9, 23),
                             _dt.date(2026, 9, 24), adjustment_observations=4)
    assert v == "APPLIED" and ev["ca_adjustment_observations"] == 4


def test_small_factors_are_not_guessed():
    v, ev = vendor_treatment(D("1.1"), D("100"), D("91"), LATE, _dt.date(2026, 3, 1))
    assert v == "UNKNOWN" and "too close to 1" in ev["why"]


def test_no_factor_is_not_applicable():
    assert vendor_treatment(None, None, None, None, _dt.date(2026, 1, 1))[0] == "N/A"
