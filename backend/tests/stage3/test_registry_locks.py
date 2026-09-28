"""Registry coverage, snapshot instants, the no-vendor import guard and every
execution-lock condition (without a database: the DB-backed lock checks are in
test_engine.py)."""

from __future__ import annotations

import ast
import datetime as _dt
import json
import pathlib

import pytest

from app.core.clock import IST
from app.features import locks
from app.features import registry as R
from app.features.compute import REASONS
from app.features.decisions import DECISIONS
from app.features.snapshots import NoSnapshot, as_of_for

FEATURES_DIR = pathlib.Path(__file__).resolve().parents[2] / "app" / "features"


class TestRegistry:
    def test_every_diagram_group_and_item_is_registered_once(self):
        groups = {d["group"] for d in R.DIAGRAM}
        assert groups == {"price_technical", "volume_liquidity", "fundamental", "event",
                          "market_context", "preopen"}
        items = [d["item"] for d in R.DIAGRAM]
        assert len(items) == len(set(items)) == 31

    def test_every_item_is_classified_and_non_implemented_items_say_why(self):
        for d in R.DIAGRAM:
            st = R.diagram_status(d)
            assert st in ("IMPLEMENTED", "PARTIAL", "UNSUPPORTED", "UNKNOWN")
            if st in ("UNSUPPORTED", "UNKNOWN"):
                assert d["reason"] and not d["features"]
            if st == "PARTIAL":
                assert d["partial"] and d["features"]

    def test_diagram_features_exist_and_every_feature_is_reachable(self):
        named = {f for d in R.DIAGRAM for f in d["features"]}
        assert named <= set(R.BY_ID)
        assert set(R.BY_ID) == named

    def test_specs_are_complete_and_unique(self):
        assert len(R.BY_ID) == len(R.FEATURES)
        for f in R.FEATURES:
            assert f.status == "IMPLEMENTED" and f.group and f.definition and f.inputs
            assert f.param_status in ("SPECIFIED", "PROPOSED")
            assert f.scope in ("INSTRUMENT", "CONTEXT")
            assert set(f.snapshots) <= {"PRE_SESSION", "PRE_OPEN"}
            if f.group == "preopen":
                assert f.snapshots == ("PRE_OPEN",)

    def test_proposed_parameters_are_approved(self):
        assert any(f.param_status == "PROPOSED" for f in R.FEATURES)
        assert all(d["status"] == "APPROVED" for d in DECISIONS.values())

    def test_registry_hash_is_stable_and_definition_sensitive(self):
        doc = R.registry_document()
        again = json.loads(json.dumps(doc, default=str))
        assert R.REGISTRY_SHA256 == R.REGISTRY_SHA256
        assert again["version"] == R.VERSION and len(R.REGISTRY_SHA256) == 64


class TestSnapshots:
    D = _dt.date(2026, 9, 24)

    def test_normal_session(self):
        ps = as_of_for(self.D, "PRE_SESSION", preopen_start=_dt.time(9), open_time=_dt.time(9, 15))
        po = as_of_for(self.D, "PRE_OPEN", preopen_start=_dt.time(9), open_time=_dt.time(9, 15))
        assert ps == _dt.datetime(2026, 9, 24, 8, 59, 59, tzinfo=IST)
        assert po == _dt.datetime(2026, 9, 24, 9, 8, tzinfo=IST)
        assert ps.tzinfo == _dt.UTC

    def test_session_without_preopen(self):
        ps = as_of_for(self.D, "PRE_SESSION", preopen_start=None, open_time=_dt.time(18, 15))
        assert ps == _dt.datetime(2026, 9, 24, 18, 14, 59, tzinfo=IST)
        with pytest.raises(NoSnapshot):
            as_of_for(self.D, "PRE_OPEN", preopen_start=None, open_time=_dt.time(18, 15))

    def test_unknown_or_timeless(self):
        with pytest.raises(NoSnapshot):
            as_of_for(self.D, "CLOSE", preopen_start=_dt.time(9), open_time=None)
        with pytest.raises(NoSnapshot):
            as_of_for(self.D, "PRE_SESSION", preopen_start=None, open_time=None)


class TestImportGuard:
    """Stage 3 must not be able to reach a vendor or start Stage 1 ingestion."""

    FORBIDDEN = ("app.vendor", "httpx", "requests", "aiohttp", "websockets", "socket")

    def imports(self):
        for p in FEATURES_DIR.rglob("*.py"):
            for node in ast.walk(ast.parse(p.read_text())):
                if isinstance(node, ast.Import):
                    yield p, [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    yield p, [node.module]

    def test_no_vendor_or_fetch_imports(self):
        bad = [(p.name, m) for p, mods in self.imports() for m in mods
               if any(m == f or m.startswith(f + ".") for f in self.FORBIDDEN)]
        assert bad == []

    def test_only_the_ledger_is_used_from_ingest(self):
        ingest = {m for _, mods in self.imports() for m in mods if m.startswith("app.ingest")}
        assert ingest <= {"app.ingest.runner"}


class TestLockPieces:
    def test_flags_default_off(self):
        from app.core.config import Settings
        f = Settings.model_fields
        assert f["PRAJNA_STAGE3_ENABLED"].default is False
        assert f["PRAJNA_STAGE3_BACKFILL_ENABLED"].default is False

    def test_kill_switch(self, tmp_path, monkeypatch):
        monkeypatch.setattr(locks, "KILL_FILE", tmp_path / "run" / "stage3.kill")
        assert not locks.kill_switch_engaged()
        locks.set_kill_switch(True, "test")
        assert locks.kill_switch_engaged()
        assert json.loads(locks.KILL_FILE.read_text())["reason"] == "test"
        locks.set_kill_switch(False)
        assert not locks.kill_switch_engaged()

    def report(self, path, overall="PASS", p="PASS", age_days=1):
        gen = _dt.datetime(2026, 9, 28, tzinfo=_dt.UTC) - _dt.timedelta(days=age_days)
        path.write_text(json.dumps({"generated_at": gen.isoformat(), "overall": overall,
                                    "criteria": [{"id": "P", "status": p}]}))
        return path

    AT = _dt.datetime(2026, 9, 28, tzinfo=_dt.UTC)

    def test_stage2_report_rules(self, tmp_path):
        f = tmp_path / "s2.json"
        assert locks.stage2_status(f, at=self.AT)[0] is False             # missing
        assert locks.stage2_status(self.report(f), at=self.AT)[0] is True
        assert locks.stage2_status(self.report(f, overall="FAIL"), at=self.AT)[0] is False
        assert locks.stage2_status(self.report(f, p="NOT_RUN"), at=self.AT)[0] is False
        assert locks.stage2_status(self.report(f, age_days=8), at=self.AT)[0] is False
        f.write_text("{not json")
        assert locks.stage2_status(f, at=self.AT)[0] is False

    def test_registry_consistent(self):
        assert locks.registry_status()[0] is True

    def test_lock_report(self):
        r = locks.LockReport("RUN")
        assert not r.ok                                   # no conditions: never unlocked
        r.add("a", True, "x")
        assert r.ok
        r.add("b", False, "y")
        assert not r.ok and r.summary()["failing"] == ["b"]
        assert "b: y" in str(locks.LockRefused(r))

    def test_reasons_are_closed(self):
        assert set(REASONS) == {"MISSING_INPUT", "INSUFFICIENT_HISTORY", "MALFORMED_INPUT",
                                "NOT_APPLICABLE", "DIVISION_UNDEFINED", "UNSUPPORTED", "UNKNOWN"}
