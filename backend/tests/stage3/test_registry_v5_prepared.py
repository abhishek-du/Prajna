"""ca_days_to_* registered UNSUPPORTED (CA-TO-UNSUPPORTED, prepared 2026-10-13; ACTIVE with
features-v5 since 2026-10-21). Against the features-v4 list it changes exactly the four
features and the one diagram item, and the engine drops exactly those four rows and changes
no other value."""

from __future__ import annotations

from dataclasses import asdict

import pytest

from app.core import clock
from app.features import engine as E
from app.features import registry as R
from app.features import snapshots as SN
from tests.stage3.test_engine import world  # noqa: F401  (fixture)
from tests.support import stage3_seed as W

V4_SHA = "6f998a76c49462c3244b5eecb2d783e75c6fff9d26365ae3540c8e88dbb201c3"


def test_the_v4_list_is_all_implemented_and_v5_has_the_four_unsupported():
    assert R.CA_TO_UNSUPPORTED_ACTIVE is True and R.VERSION == "features-v5"
    assert all(f.status == "IMPLEMENTED" for f in R.FEATURES_V4) and len(R.FEATURES_V4) == 104
    assert {f.id for f in R.FEATURES if f.status == "UNSUPPORTED"} == set(R.CA_TO_FEATURES)


def test_ca_to_changes_exactly_the_four_features_and_one_diagram_item():
    from dataclasses import asdict as _a
    new = {f.id: _a(f) for f in R.apply_ca_to_unsupported(R.FEATURES_V4)}
    old = {f.id: _a(f) for f in R.FEATURES_V4}
    assert new.keys() == old.keys()                         # still registered, none removed
    changed = {k for k in new if new[k] != old[k]}
    assert changed == set(R.CA_TO_FEATURES)
    for k in changed:
        assert new[k]["status"] == "UNSUPPORTED"
        assert new[k]["version"] == old[k]["version"]
        assert R.CA_TO_UNSUPPORTED_REASON in new[k]["definition"]
    ca = next(d for d in R.DIAGRAM if d["item"] == "Corporate actions")
    assert R.CA_TO_UNSUPPORTED_REASON in ca["partial"]


def test_active_v5_still_satisfies_acceptance_a():
    """Criterion A: every UNSUPPORTED/UNKNOWN item has a reason, every PARTIAL item a
    'partial' note, and every listed feature id is registered."""
    doc = R.registry_document()
    ids = {f["id"] for f in doc["features"]}
    bad = [d["item"] for d in doc["diagram"]
           if (R.diagram_status(d) in ("UNSUPPORTED", "UNKNOWN") and not d.get("reason"))
           or (R.diagram_status(d) == "PARTIAL" and not d.get("partial"))]
    assert not bad and all(f in ids for d in doc["diagram"] for f in d["features"])
    ca = next(d for d in doc["diagram"] if d["item"] == "Corporate actions")
    assert R.diagram_status(ca) == "PARTIAL"


def test_lock_registry_check_ignores_unsupported_specs(monkeypatch):
    from app.features import locks
    monkeypatch.setattr(locks, "FEATURES", R.FEATURES)
    assert locks.registry_status() == (True, "consistent")


@pytest.mark.db
@pytest.mark.integration
async def test_engine_drops_exactly_the_four_rows_and_changes_nothing_else(world,  # noqa: F811
                                                                           monkeypatch):
    clock.freeze(W.NOW)
    snap = await SN.resolve(world, W.SESSION, "PRE_SESSION")
    keys = [W.A, W.B]
    monkeypatch.setattr(E, "FEATURES", R.FEATURES_V4)
    before = await E.compute_snapshot(world, snap, keys)
    monkeypatch.setattr(E, "FEATURES", R.apply_ca_to_unsupported(R.FEATURES_V4))
    after = await E.compute_snapshot(world, snap, keys)
    b = {(r.instrument_key, r.feature_id): asdict(r) for r in before.rows}
    a = {(r.instrument_key, r.feature_id): asdict(r) for r in after.rows}
    dropped = set(b) - set(a)
    assert not set(a) - set(b)
    assert {f for _, f in dropped} == set(R.CA_TO_FEATURES)
    assert len(dropped) == len(keys) * 4
    assert all(a[k] == b[k] for k in a)                     # every other row identical
