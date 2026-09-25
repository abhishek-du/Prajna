"""Token security (hardening phase 1): the write token never reaches argv,
ingest_run, runbooks or cron; historical rows can be redacted auditably.

Real incident (2026-09-25): the Prajna write token sat in 24,674
ingest_run.argv rows and in `ps` output, because runbooks passed
`--token "$TOKEN"` and the runner stored sys.argv verbatim."""

from __future__ import annotations

import datetime as _dt
import os
import pathlib
import re
import sys
import uuid

import pytest
from sqlalchemy import text

from app.core.authz import REDACTED, redact_argv
from app.core.errors import AuthorizationError
from app.ingest.redact import redact_run_argv
from app.ingest.runner import IngestRunner

TOKEN = os.environ["PRAJNA_WRITE_TOKEN"]
BACKEND = pathlib.Path(__file__).resolve().parents[2]


class TestRedactArgv:
    def test_both_flag_forms_and_embedded_values_are_redacted(self):
        argv = ["main.py", "ingest", "news", "--commit", "--token", TOKEN,
                f"--token={TOKEN}", f"x{TOKEN}y", "--timeframe", "1m"]
        out = redact_argv(argv)
        assert out == ["main.py", "ingest", "news", "--commit", "--token", REDACTED,
                       f"--token={REDACTED}", f"x{REDACTED}y", "--timeframe", "1m"]
        assert not any(TOKEN in a for a in out)

    def test_an_unknown_token_after_the_flag_is_redacted_too(self):
        assert redact_argv(["p", "--token", "some-other-secret"]) == ["p", "--token", REDACTED]

    def test_argv_without_secrets_is_unchanged(self):
        argv = ["main.py", "--plain", "ingest", "candles", "--key", "NSE_EQ|INE002A01018"]
        assert redact_argv(argv) == argv


def _runner(s):
    return IngestRunner(s, source="UPSTOX_ASSETS", stream="test.token", operator="pytest",
                        vendor_endpoint="https://assets.upstox.com/test")


@pytest.mark.db
@pytest.mark.integration
class TestRunLedger:
    async def test_runner_never_stores_the_token(self, db_session, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["main.py", "ingest", "x", "--commit", "--token", TOKEN])
        ctx = await _runner(db_session).open(commit=True, token=TOKEN)
        argv = (await db_session.execute(text("select argv from ingest_run where run_id=:r"),
                                         {"r": ctx.run_id})).scalar()
        assert argv == ["main.py", "ingest", "x", "--commit", "--token", REDACTED]

    async def test_commit_without_a_token_is_still_refused(self, db_session):
        with pytest.raises(AuthorizationError):
            await _runner(db_session).open(commit=True, token=None)
        with pytest.raises(AuthorizationError):
            await _runner(db_session).open(commit=True, token="wrong")

    async def _seed(self, s, status, argv):
        rid = uuid.uuid4()
        await s.execute(text("""
            insert into ingest_run (run_id, source, stream, vendor_endpoint, request_params,
              code_git_sha, config_sha256, argv, operator, mode, status, authz_token_sha256,
              started_at, finished_at, rows_written)
            values (:r, 'UPSTOX_ASSETS', 'test.seed', 't', '{}', 't', :c, :a, 'pytest',
                    'COMMIT', :st, :h, now(),
                    :fin, 0)"""),
            {"r": rid, "c": "c" * 64, "a": argv, "st": status, "h": "a" * 64,
             "fin": None if status == "RUNNING" else _dt.datetime.now(_dt.UTC)})
        return rid

    async def test_redaction_is_authorized_audited_idempotent_and_skips_running(self, db_session):
        s = db_session
        done = await self._seed(s, "COMPLETE", ["main.py", "--commit", "--token", TOKEN])
        eq = await self._seed(s, "FAILED", ["main.py", f"--token={TOKEN}"])
        running = await self._seed(s, "RUNNING", ["main.py", "--token", TOKEN])
        clean = await self._seed(s, "COMPLETE", ["main.py", "db", "tables"])
        with pytest.raises(AuthorizationError):
            await redact_run_argv(s, commit=True, token=None)

        dry = await redact_run_argv(s, commit=False, token=None)
        assert dry["runs_to_redact"] >= 2 and dry["runs_redacted"] == 0
        assert (await s.execute(text("select argv from ingest_run where run_id=:r"),
                                {"r": done})).scalar()[-1] == TOKEN     # dry run: untouched

        rep = await redact_run_argv(s, commit=True, token=TOKEN)
        assert rep["running_skipped"] >= 1
        rows = dict((await s.execute(text(
            "select run_id, argv from ingest_run where run_id = any(:r)"),
            {"r": [done, eq, running, clean]})).all())
        assert rows[done] == ["main.py", "--commit", "--token", REDACTED]
        assert rows[eq] == ["main.py", f"--token={REDACTED}"]
        assert rows[running][-1] == TOKEN                  # still RUNNING: left for later
        assert rows[clean] == ["main.py", "db", "tables"]
        ledger = (await s.execute(text(
            "select source, stream, status, request_params->'outcome' from ingest_run "
            "where run_id = :r"), {"r": uuid.UUID(rep["run_id"])})).one()
        assert ledger[:3] == ("PRAJNA_MAINT", "maint.redact_argv", "COMPLETE")
        assert ledger[3]["runs_redacted"] == rep["runs_redacted"]

        again = await redact_run_argv(s, commit=True, token=TOKEN)
        assert again["runs_to_redact"] == 0                # idempotent
        n = (await s.execute(text(
            "select count(*) from ingest_run where status <> 'RUNNING' "
            "and array_to_string(argv, ' ') like '%' || :t || '%'"), {"t": TOKEN})).scalar()
        assert n == 0


class TestNoSecretInArgvAnywhere:
    def test_every_token_option_reads_the_environment(self):
        import typer.main

        from app.cli.main import app
        cmd = typer.main.get_command(app)
        found = []

        def walk(c):
            for p in getattr(c, "params", []):
                if "--token" in getattr(p, "opts", []):
                    found.append((c.name, p.envvar))
            for sub in getattr(c, "commands", {}).values():
                walk(sub)
        walk(cmd)
        assert len(found) >= 12
        assert all(env == "PRAJNA_SUPPLIED_TOKEN" for _, env in found), found

    def test_runbooks_and_cron_never_pass_a_token_in_argv(self):
        files = list((BACKEND / "ops" / "runbooks").glob("*.sh")) + [
            BACKEND / "ops" / "cron" / "prajna.cron"]
        offenders = [f"{f.name}:{i}" for f in files
                     for i, line in enumerate(f.read_text().splitlines(), 1)
                     if re.search(r"--token[ =]", line) and not line.lstrip().startswith("#")]
        assert offenders == []
