"""The pure lifecycle/attribute diff of the daily master refresh (phase 2)."""

from __future__ import annotations

from app.ingest.instrument_refresh import diff_master
from app.ingest.instruments import ATTRIBUTES


def _attrs(**kw):
    base = {c: None for c in ATTRIBUTES}
    base.update(segment="NSE_EQ", exchange="NSE", trading_symbol="X", instrument_type="EQ",
                lot_size=1)
    base.update(kw)
    return base


def _cur(status="ACTIVE", **kw):
    return {**_attrs(**kw), "lifecycle_status": status, "instrument_id": 1}


def test_new_seen_and_attribute_change():
    d = diff_master(selected={"A": _attrs(), "B": _attrs(lot_size=2), "N": _attrs()},
                    in_master={"A": _attrs(), "B": _attrs(lot_size=2)},
                    current={"A": _cur(), "B": _cur(lot_size=1)}, rejected=set(),
                    recovered=set())
    assert d.new == ["N"] and d.seen == ["A", "B"]
    assert d.changed == {"B": {"lot_size": (1, 2)}}
    assert d.transitions == {}


def test_removed_and_ineligible_are_distinct():
    d = diff_master(selected={}, in_master={"I": _attrs(instrument_type="N1")},
                    current={"R": _cur(), "I": _cur()}, rejected=set(), recovered=set())
    assert d.transitions["R"][:2] == ("ACTIVE", "REMOVED_FROM_MASTER")
    assert d.transitions["I"][:2] == ("ACTIVE", "INELIGIBLE")
    assert d.changed["I"] == {"instrument_type": ("EQ", "N1")}


def test_vendor_rejection_then_recovery():
    cur = {"V": _cur()}
    d = diff_master(selected={"V": _attrs()}, in_master={"V": _attrs()}, current=cur,
                    rejected={"V"}, recovered=set())
    assert d.transitions["V"][:2] == ("ACTIVE", "VENDOR_REJECTED")
    # still rejected, no COMPLETE run since: stays
    d = diff_master(selected={"V": _attrs()}, in_master={"V": _attrs()},
                    current={"V": _cur("VENDOR_REJECTED")}, rejected={"V"}, recovered=set())
    assert d.transitions == {}
    # a COMPLETE run after the rejection: back to ACTIVE
    d = diff_master(selected={"V": _attrs()}, in_master={"V": _attrs()},
                    current={"V": _cur("VENDOR_REJECTED")}, rejected={"V"}, recovered={"V"})
    assert d.transitions["V"][:2] == ("VENDOR_REJECTED", "ACTIVE")


def test_precedence_removed_over_rejected():
    d = diff_master(selected={}, in_master={}, current={"V": _cur()}, rejected={"V"},
                    recovered=set())
    assert d.transitions["V"][1] == "REMOVED_FROM_MASTER"


def test_reappearance_returns_to_active():
    d = diff_master(selected={"R": _attrs()}, in_master={"R": _attrs()},
                    current={"R": _cur("REMOVED_FROM_MASTER")}, rejected=set(),
                    recovered=set())
    assert d.transitions["R"] == ("REMOVED_FROM_MASTER", "ACTIVE",
                                  "reappeared in the vendor master")
    assert d.new == []                        # same key: never a second identity
