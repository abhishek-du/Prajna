"""features-v5 (PREPARED, NOT ACTIVE): ca_days_to_* registered UNSUPPORTED.

While CA_TO_UNSUPPORTED_ACTIVE is False the active registry must stay byte-identical
to features-v4 (every stored row, manifest and evidence hash refers to it). The
prepared document changes exactly the four features and the one diagram item, and
the engine - given the prepared feature list - drops exactly those four rows and
changes no other value."""

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
V5_SHA = "f415cebf11c5dc50599be4a885a904e96b0bc53bc044758527be16c9d29217f6"


def test_inactive_registry_is_still_features_v4_byte_for_byte():
    assert R.CA_TO_UNSUPPORTED_ACTIVE is False
    assert R.VERSION == "features-v4" and R.REGISTRY_SHA256 == V4_SHA
    assert all(f.status == "IMPLEMENTED" for f in R.FEATURES) and len(R.FEATURES) == 104


def test_prepared_v5_changes_exactly_the_four_features_and_one_diagram_item():
    doc, cur = R.ca_to_unsupported_document(), R.registry_document()
    assert doc["version"] == "features-v5" and R.CA_TO_UNSUPPORTED_SHA256 == V5_SHA != V4_SHA
    new = {f["id"]: f for f in doc["features"]}
    old = {f["id"]: f for f in cur["features"]}
    assert new.keys() == old.keys()                         # still registered, none removed
    changed = {k for k in new if new[k] != old[k]}
    assert changed == set(R.CA_TO_FEATURES)
    for k in changed:
        assert new[k]["status"] == "UNSUPPORTED"
        assert new[k]["version"] == old[k]["version"]
        assert R.CA_TO_UNSUPPORTED_REASON in new[k]["definition"]
    diff = [n["item"] for n, o in zip(doc["diagram"], cur["diagram"], strict=True) if n != o]
    assert diff == ["Corporate actions"]


def test_prepared_v5_still_satisfies_acceptance_a():
    """Criterion A: every UNSUPPORTED/UNKNOWN item has a reason, every PARTIAL item a
    'partial' note, and every listed feature id is registered."""
    doc = R.ca_to_unsupported_document()
    ids = {f["id"] for f in doc["features"]}
    bad = [d["item"] for d in doc["diagram"]
           if (R.diagram_status(d) in ("UNSUPPORTED", "UNKNOWN") and not d.get("reason"))
           or (R.diagram_status(d) == "PARTIAL" and not d.get("partial"))]
    assert not bad and all(f in ids for d in doc["diagram"] for f in d["features"])
    ca = next(d for d in doc["diagram"] if d["item"] == "Corporate actions")
    assert R.diagram_status(ca) == "PARTIAL"


def test_lock_registry_check_ignores_unsupported_specs(monkeypatch):
    from app.features import locks
    monkeypatch.setattr(locks, "FEATURES", R.apply_ca_to_unsupported(R.FEATURES))
    assert locks.registry_status() == (True, "consistent")


@pytest.mark.db
@pytest.mark.integration
async def test_engine_drops_exactly_the_four_rows_and_changes_nothing_else(world,  # noqa: F811
                                                                           monkeypatch):
    clock.freeze(W.NOW)
    snap = await SN.resolve(world, W.SESSION, "PRE_SESSION")
    keys = [W.A, W.B]
    before = await E.compute_snapshot(world, snap, keys)
    monkeypatch.setattr(E, "FEATURES", R.apply_ca_to_unsupported(R.FEATURES))
    after = await E.compute_snapshot(world, snap, keys)
    b = {(r.instrument_key, r.feature_id): asdict(r) for r in before.rows}
    a = {(r.instrument_key, r.feature_id): asdict(r) for r in after.rows}
    dropped = set(b) - set(a)
    assert not set(a) - set(b)
    assert {f for _, f in dropped} == set(R.CA_TO_FEATURES)
    assert len(dropped) == len(keys) * 4
    assert all(a[k] == b[k] for k in a)                     # every other row identical
