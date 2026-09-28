"""BUG-CLI-STAGE2-STAGE3-DEFAULT-PATHS-UNANCHORED (independent audit, 2026-09-28):
The Stage 2 and Stage 3 acceptance CLI commands previously defaulted to unanchored
paths ("var/acceptance/stage2.json", "../docs/STAGE_2_ACCEPTANCE.md"). Run from
the repository root, the markdown output was written outside the repository
(../docs/); run from backend/ or arbitrary CWD, behavior was inconsistent.
All acceptance commands now anchor default outputs to BACKEND_ROOT / docs.
"""

from __future__ import annotations

import os
import pathlib
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from app.acceptance import stage2 as S2
from app.acceptance import stage3 as S3
from app.cli.main import app
from app.core.config import BACKEND_ROOT


@pytest.fixture
def isolated_dirs(tmp_path, monkeypatch):
    """Isolated fake repo and unrelated directories."""
    repo = tmp_path / "prajna_repo"
    backend = repo / "backend"
    docs = repo / "docs"
    var_acc = backend / "var" / "acceptance"
    var_acc.mkdir(parents=True)
    docs.mkdir(parents=True)

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir(parents=True)

    import app.acceptance.stage1 as S1
    monkeypatch.setattr(S1, "BACKEND_ROOT", backend)
    return repo, backend, docs, elsewhere


def test_stage2_cli_default_outputs_are_anchored(isolated_dirs, monkeypatch):
    repo, backend, docs, elsewhere = isolated_dirs

    async def fake_evaluate(_s, _tests, seed=None):
        return {
            "generated_at": "2026-09-28T20:00:00+05:30",
            "overall": "PASS",
            "criteria": [{"id": "A", "status": "PASS", "question": "q"}]
        }

    monkeypatch.setattr(S2, "evaluate", fake_evaluate)
    monkeypatch.setattr(S2, "to_markdown", lambda rep, notes=None: "# Stage 2 Acceptance\n")

    # Run from unrelated directory
    monkeypatch.chdir(elsewhere)
    with patch("app.db.engine.get_sessionmaker") as mock_sm:
        mock_session = AsyncMock()
        from unittest.mock import MagicMock
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_sm.return_value.return_value.__aenter__.return_value = mock_session

        runner = CliRunner()
        result = runner.invoke(app, ["--plain", "acceptance", "stage2"])
        assert result.exit_code == 0, result.output

    # Verify defaults landed in anchored project directories
    assert (backend / "var" / "acceptance" / "stage2.json").is_file()
    assert (docs / "STAGE_2_ACCEPTANCE.md").is_file()
    # Verify nothing was written in the unrelated working directory
    assert not list(elsewhere.rglob("*"))


def test_stage2_cli_explicit_paths_respected(isolated_dirs, monkeypatch):
    repo, backend, docs, elsewhere = isolated_dirs

    async def fake_evaluate(_s, _tests, seed=None):
        return {
            "generated_at": "2026-09-28T20:00:00+05:30",
            "overall": "PASS",
            "criteria": [{"id": "A", "status": "PASS", "question": "q"}]
        }

    monkeypatch.setattr(S2, "evaluate", fake_evaluate)

    monkeypatch.chdir(elsewhere)
    with patch("app.db.engine.get_sessionmaker") as mock_sm:
        mock_session = AsyncMock()
        from unittest.mock import MagicMock
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_sm.return_value.return_value.__aenter__.return_value = mock_session

        runner = CliRunner()
        result = runner.invoke(app, ["--plain", "acceptance", "stage2", "--out", "custom_s2.json", "--md", ""])
        assert result.exit_code == 0, result.output

    assert (elsewhere / "custom_s2.json").is_file()
    assert not (elsewhere / "STAGE_2_ACCEPTANCE.md").exists()


def test_stage3_cli_default_outputs_are_anchored(isolated_dirs, monkeypatch):
    repo, backend, docs, elsewhere = isolated_dirs

    async def fake_evaluate(_s, _tests):
        return {
            "generated_at": "2026-09-28T20:00:00+05:30",
            "overall": "COMPLETE",
            "criteria": [{"id": "A", "status": "PASS", "question": "q"}],
            "levels": [{"level": "PRODUCTION READY", "reached": True}]
        }

    monkeypatch.setattr(S3, "evaluate", fake_evaluate)
    monkeypatch.setattr(S3, "to_markdown", lambda rep: "# Stage 3 Acceptance\n")

    monkeypatch.chdir(elsewhere)
    with patch("app.db.engine.get_sessionmaker") as mock_sm:
        mock_session = AsyncMock()
        mock_sm.return_value.return_value.__aenter__.return_value = mock_session

        runner = CliRunner()
        result = runner.invoke(app, ["--plain", "acceptance", "stage3"])
        assert result.exit_code == 0, result.output

    # Verify defaults landed in anchored project directories
    assert (backend / "var" / "acceptance" / "stage3.json").is_file()
    assert (docs / "STAGE_3_ACCEPTANCE.md").is_file()
    # Verify nothing was written in the unrelated working directory
    assert not list(elsewhere.rglob("*"))


def test_stage3_cli_explicit_paths_respected(isolated_dirs, monkeypatch):
    repo, backend, docs, elsewhere = isolated_dirs

    async def fake_evaluate(_s, _tests):
        return {
            "generated_at": "2026-09-28T20:00:00+05:30",
            "overall": "COMPLETE",
            "criteria": [{"id": "A", "status": "PASS", "question": "q"}],
            "levels": [{"level": "PRODUCTION READY", "reached": True}]
        }

    monkeypatch.setattr(S3, "evaluate", fake_evaluate)

    monkeypatch.chdir(elsewhere)
    with patch("app.db.engine.get_sessionmaker") as mock_sm:
        mock_session = AsyncMock()
        mock_sm.return_value.return_value.__aenter__.return_value = mock_session

        runner = CliRunner()
        result = runner.invoke(app, ["--plain", "acceptance", "stage3", "--out", "custom_s3.json", "--md", ""])
        assert result.exit_code == 0, result.output

    assert (elsewhere / "custom_s3.json").is_file()
    assert not (elsewhere / "STAGE_3_ACCEPTANCE.md").exists()


def test_stage2_stage3_from_repo_root_and_backend_root(isolated_dirs, monkeypatch):
    """Verify that stage2 and stage3 acceptance commands write to the exact same anchored
    paths whether invoked from repository root or backend directory."""
    repo, backend, docs, elsewhere = isolated_dirs

    async def fake_evaluate_s2(_s, _tests, seed=None):
        return {
            "generated_at": "2026-09-28T20:00:00+05:30",
            "overall": "PASS",
            "criteria": [{"id": "A", "status": "PASS", "question": "q"}]
        }

    async def fake_evaluate_s3(_s, _tests):
        return {
            "generated_at": "2026-09-28T20:00:00+05:30",
            "overall": "COMPLETE",
            "criteria": [{"id": "A", "status": "PASS", "question": "q"}],
            "levels": [{"level": "PRODUCTION READY", "reached": True}]
        }

    monkeypatch.setattr(S2, "evaluate", fake_evaluate_s2)
    monkeypatch.setattr(S2, "to_markdown", lambda rep, notes=None: "# Stage 2 Acceptance\n")
    monkeypatch.setattr(S3, "evaluate", fake_evaluate_s3)
    monkeypatch.setattr(S3, "to_markdown", lambda rep: "# Stage 3 Acceptance\n")

    from unittest.mock import MagicMock

    for cwd in (repo, backend):
        monkeypatch.chdir(cwd)
        with patch("app.db.engine.get_sessionmaker") as mock_sm:
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.all.return_value = []
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_sm.return_value.return_value.__aenter__.return_value = mock_session

            runner = CliRunner()
            res2 = runner.invoke(app, ["--plain", "acceptance", "stage2"])
            assert res2.exit_code == 0, res2.output

            res3 = runner.invoke(app, ["--plain", "acceptance", "stage3"])
            assert res3.exit_code == 0, res3.output

        assert (backend / "var" / "acceptance" / "stage2.json").is_file()
        assert (docs / "STAGE_2_ACCEPTANCE.md").is_file()
        assert (backend / "var" / "acceptance" / "stage3.json").is_file()
        assert (docs / "STAGE_3_ACCEPTANCE.md").is_file()
        # Verify no rogue docs/ or var/ directories were created at repo root
        assert not (repo / "var").exists()

