"""BUG-STAGE1-CLI-CWD-RELATIVE-PATHS (independent audit, 2026-09-28): the Stage 1
gate read var/acceptance/preopen_*.json (K), var/logs/daily/close_then_backfill_*.log
(R) and var/acceptance/b1b2.json (X) relative to the WORKING directory. Run from
the repository root it found none of them and reported NOT COMPLETE (K FAIL, R and
X waiting) while the same database gave COMPLETE from backend/. Every file the
gate reads (and its default outputs) is now anchored to the backend directory."""

from __future__ import annotations

import json
import os

import pytest
from typer.testing import CliRunner

from app.acceptance import stage1 as S1
from app.core.config import BACKEND_ROOT


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A project tree <tmp>/repo/backend with the gate's evidence files."""
    backend = tmp_path / "repo" / "backend"
    acc, logs = backend / "var" / "acceptance", backend / "var" / "logs" / "daily"
    acc.mkdir(parents=True)
    logs.mkdir(parents=True)
    (tmp_path / "repo" / "docs").mkdir()
    (acc / "preopen_2026-09-28.json").write_text(json.dumps({
        "verdict": "PASS", "real_market_data": True,
        "checks": [{"id": "C6", "status": "WARN"}, {"id": "C1", "status": "PASS"}],
        "B7": {"status": "OBSERVED"}, "B8": {"status": "RESOLVED"}}))
    (acc / "b1b2.json").write_text(json.dumps({"B1": {"status": "VERIFIED"},
                                               "B2": {"status": "VERIFIED"}}))
    (logs / "close_then_backfill_2026-09-28.log").write_text(
        "[2026-09-28 16:40:00 IST] CLOSE_RERUN_CHECK jobs=9 complete=9 inserted=0 "
        "failed=0 idempotent=True\n")
    monkeypatch.setattr(S1, "BACKEND_ROOT", backend)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    return backend, elsewhere


def evidence():
    return S1.preopen_report(), S1.rerun_checks(), S1.load_b1b2()


def test_backend_root_is_the_backend_directory():
    assert (BACKEND_ROOT / "app" / "acceptance" / "stage1.py").is_file()
    assert (BACKEND_ROOT / "pyproject.toml").is_file()
    assert S1.anchored("var/acceptance/b1b2.json") == BACKEND_ROOT / "var/acceptance/b1b2.json"
    assert S1.anchored("/abs/x.json").as_posix() == "/abs/x.json"


def test_same_evidence_from_backend_repo_root_and_any_other_directory(project, monkeypatch):
    backend, elsewhere = project
    seen = []
    for cwd in (backend, backend.parent, elsewhere, backend / "var"):
        monkeypatch.chdir(cwd)
        seen.append(evidence())
    assert all(x == seen[0] for x in seen)
    (k_status, k_ev), reruns, b1b2 = seen[0]
    assert k_status == S1.PASS and k_ev["non_pass"] == {"C6": "WARN"}
    assert k_ev["report"] == "var/acceptance/preopen_2026-09-28.json"   # evidence format kept
    assert reruns == ["CLOSE_RERUN_CHECK jobs=9 complete=9 inserted=0 failed=0 "
                      "idempotent=True"]
    assert b1b2["B1"]["status"] == "VERIFIED"


def test_the_real_project_reads_the_same_files_from_any_directory(tmp_path, monkeypatch):
    """The audit's exact scenario on this checkout: backend/ vs the repository root."""
    seen = []
    for cwd in (BACKEND_ROOT, BACKEND_ROOT.parent, tmp_path):
        monkeypatch.chdir(cwd)
        seen.append(evidence())
    assert seen[0] == seen[1] == seen[2]


def test_relative_archive_uris_resolve_against_the_backend(project, monkeypatch):
    backend, elsewhere = project
    import gzip

    from app.contracts.provenance import payload_sha256
    data = b'{"x": 1}'
    rel = "var/archive/T/2026/09/28/a.json.gz"
    (backend / rel).parent.mkdir(parents=True)
    (backend / rel).write_bytes(gzip.compress(data))
    monkeypatch.chdir(elsewhere)
    assert S1.anchored(rel).exists()
    from app.storage.payload_store import PayloadStore
    assert PayloadStore.read(S1.anchored(rel), payload_sha256(data)) == data


def test_cli_default_outputs_are_anchored(project, monkeypatch):
    backend, elsewhere = project
    from app.cli.main import app

    async def fake_evaluate(_s):
        return {"generated_at": "t", "overall": "COMPLETE", "live_readiness": "PASS",
                "criteria": [], "decisions": {}}
    monkeypatch.setattr(S1, "evaluate", fake_evaluate)
    monkeypatch.chdir(elsewhere)
    r = CliRunner().invoke(app, ["--plain", "acceptance", "stage1"])
    assert r.exit_code == 0, r.output
    assert (backend / "var" / "acceptance" / "stage1.json").is_file()
    assert (backend.parent / "docs" / "STAGE_1_FINAL_ACCEPTANCE.md").is_file()
    assert not list(elsewhere.rglob("*"))                       # nothing written in the cwd
    r = CliRunner().invoke(app, ["--plain", "acceptance", "stage1", "--out", "mine.json",
                                 "--md", ""])
    assert r.exit_code == 0 and (elsewhere / "mine.json").is_file()   # explicit: as given
    assert os.getcwd() == str(elsewhere)
