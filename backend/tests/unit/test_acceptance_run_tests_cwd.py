"""The Stage 2 and Stage 3 gates run the test suite (criteria P and K) in a
subprocess. Without a fixed working directory, pytest used whatever directory the
gate was started from (measured 2026-09-28):

  backend/          backend/pyproject.toml applies (asyncio mode, markers)
  repository root   rootdir = the root, NO configfile: 99 failed, 738 passed,
                    282 errors -> P / K recorded FAIL
  any other dir     "no tests collected" (exit 5) -> P / K recorded FAIL

Fixed in bcf10e0 (cwd=BACKEND_ROOT); these tests pin it without running the suite."""

from __future__ import annotations

import subprocess

import pytest

from app.acceptance import stage2 as S2
from app.acceptance import stage3 as S3
from app.core.config import BACKEND_ROOT


@pytest.mark.parametrize("gate", [S2, S3], ids=["stage2", "stage3"])
def test_the_suite_runs_in_the_backend_directory_whatever_the_cwd(gate, tmp_path,
                                                                   monkeypatch):
    calls = []

    def fake_run(cmd, **kw):
        calls.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, 0, stdout="7 passed in 1.00s\n", stderr="")
    monkeypatch.setattr(subprocess, "run", fake_run)
    for cwd in (BACKEND_ROOT, BACKEND_ROOT.parent, tmp_path):
        monkeypatch.chdir(cwd)
        assert gate.run_tests() == {"exit": 0, "summary": "7 passed in 1.00s"}
    assert [str(kw.get("cwd")) for _, kw in calls] == [str(BACKEND_ROOT)] * 3
    assert all("-m" in cmd and "pytest" in cmd for cmd, _ in calls)


def test_the_backend_directory_holds_the_pytest_configuration():
    text = (BACKEND_ROOT / "pyproject.toml").read_text()
    assert "[tool.pytest.ini_options]" in text and 'asyncio_mode = "auto"' in text
