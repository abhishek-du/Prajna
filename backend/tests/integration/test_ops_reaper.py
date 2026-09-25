"""Orphan-run reaper and runner identity (hardening phase 4)."""

from __future__ import annotations

import datetime as _dt
import json
import os
import socket
import subprocess
import sys
import uuid

import pytest
from sqlalchemy import text

from app.contracts.provenance import config_sha256
from app.core.errors import AuthorizationError
from app.ingest.runner import IngestRunner, boot_id
from app.ops.reaper import LEGACY_AGE, reap_runs, verdict

TOKEN = os.environ["PRAJNA_WRITE_TOKEN"]
NOW = _dt.datetime(2026, 9, 25, 12, 0, tzinfo=_dt.UTC)
HOST = socket.gethostname()


def _dead_pid() -> int:
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid                                  # reaped by us: it no longer exists


class TestVerdict:
    def test_rules(self):
        me = {"pid": os.getpid(), "host": HOST, "boot_id": boot_id()}
        assert verdict(me, NOW, at=NOW, host=HOST, boot=boot_id()) == (
            False, f"process {os.getpid()} is alive")
        dead = {**me, "pid": _dead_pid()}
        assert verdict(dead, NOW, at=NOW, host=HOST, boot=boot_id())[0] is True
        rebooted = {**me, "boot_id": "another-boot"}
        assert "rebooted" in verdict(rebooted, NOW, at=NOW, host=HOST, boot=boot_id())[1]
        other = {**me, "host": "elsewhere"}
        assert verdict(other, NOW, at=NOW, host=HOST, boot=boot_id())[0] is False
        old = NOW - LEGACY_AGE - _dt.timedelta(minutes=1)
        assert verdict(None, old, at=NOW, host=HOST, boot=None)[0] is True
        assert verdict(None, NOW - _dt.timedelta(hours=1), at=NOW, host=HOST, boot=None)[0] is False
        # a reused pid that is not a python process is not our run
        assert verdict(me, NOW, at=NOW, host=HOST, boot=boot_id(),
                       alive=lambda pid: False)[0] is True


@pytest.mark.db
@pytest.mark.integration
class TestReaperDb:
    async def _run(self, s, runner, started):
        rid = uuid.uuid4()
        params = {"x": 1} if runner is None else {"x": 1, "runner": runner}
        await s.execute(text("""
            insert into ingest_run (run_id, source, stream, vendor_endpoint, request_params,
              code_git_sha, config_sha256, argv, operator, mode, status, authz_token_sha256,
              started_at, rows_written)
            values (:r, 'UPSTOX_REST_V3', 'ohlcv.1m.test', 't', cast(:p as jsonb), 't', :c,
                    ARRAY['x'], 'pytest', 'COMMIT', 'RUNNING', :h, :t, 0)"""),
            {"r": rid, "p": json.dumps(params), "c": "c" * 64, "h": "a" * 64, "t": started})
        return rid

    async def test_reaps_only_provable_orphans(self, db_session):
        s = db_session
        now = _dt.datetime.now(_dt.UTC)
        me = {"pid": os.getpid(), "host": HOST, "boot_id": boot_id()}
        alive = await self._run(s, me, now)
        dead = await self._run(s, {**me, "pid": _dead_pid()}, now)
        reboot = await self._run(s, {**me, "boot_id": "old-boot"}, now)
        legacy_old = await self._run(s, None, now - _dt.timedelta(hours=72))
        legacy_new = await self._run(s, None, now - _dt.timedelta(hours=2))
        with pytest.raises(AuthorizationError):
            await reap_runs(s, commit=True, token=None)
        dry = await reap_runs(s, commit=False, token=None)
        assert {o["run_id"] for o in dry["orphans"]} >= {str(dead), str(reboot), str(legacy_old)}
        rep = await reap_runs(s, commit=True, token=TOKEN)
        st = dict((await s.execute(text("select run_id, status from ingest_run where run_id = "
                                        "any(:r)"), {"r": [alive, dead, reboot, legacy_old,
                                                           legacy_new]})).all())
        assert st[alive] == "RUNNING" and st[legacy_new] == "RUNNING"
        assert st[dead] == st[reboot] == st[legacy_old] == "ABORTED"
        err = (await s.execute(text("select error from ingest_run where run_id=:r"),
                               {"r": reboot})).scalar()
        assert err.startswith("reaped by maint.reap_runs: machine rebooted")
        again = await reap_runs(s, commit=True, token=TOKEN)
        assert not {o["run_id"] for o in again["orphans"]} & {str(dead), str(reboot)}
        assert rep["committed"] is True

    async def test_runner_records_identity_outside_the_config_hash(self, db_session):
        r = IngestRunner(db_session, source="UPSTOX_ASSETS", stream="test.identity",
                         vendor_endpoint="t", request_params={"a": 1}, operator="pytest")
        ctx = await r.open(commit=False, token=None)
        row = (await db_session.execute(text(
            "select request_params, config_sha256 from ingest_run where run_id=:r"),
            {"r": ctx.run_id})).one()
        assert row.request_params["runner"] == {"pid": os.getpid(), "host": HOST,
                                                "boot_id": boot_id()}
        assert row.config_sha256 == config_sha256({"a": 1})       # identity not hashed
        await r.finalize(rows_written=0, outcome={"k": "v"})
        rp = (await db_session.execute(text("select request_params from ingest_run where "
                                            "run_id=:r"), {"r": ctx.run_id})).scalar()
        assert rp["runner"]["pid"] == os.getpid() and rp["outcome"] == {"k": "v"}


@pytest.mark.db
@pytest.mark.integration
class TestRealCrash:
    """A real process opens a COMMITTED run and is SIGKILLed mid-run: its row
    stays RUNNING; the reaper finds the dead pid and aborts exactly that run,
    while a run of a live process is left alone. Everything this test commits
    goes through its own connection and is removed again."""

    async def test_killed_process_is_reaped(self):
        import signal

        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from app.core.config import get_settings
        script = (
            "import asyncio, os, sys, time\n"
            "from app.db.engine import get_sessionmaker\n"
            "from app.ingest.runner import IngestRunner\n"
            "async def m():\n"
            "    async with get_sessionmaker()() as s:\n"
            "        r = IngestRunner(s, source='UPSTOX_REST_V3', stream='ohlcv.1m.crash-test',\n"
            "                         vendor_endpoint='t', operator='pytest')\n"
            "        ctx = await r.open(commit=True, token=os.environ['PRAJNA_WRITE_TOKEN'])\n"
            "        print(ctx.run_id, flush=True)\n"
            "        time.sleep(120)\n"
            "asyncio.run(m())\n")
        engine = create_async_engine(get_settings().PRAJNA_TEST_DATABASE_URL)
        proc = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE,
                                text=True, cwd=os.getcwd(), env=os.environ.copy())
        created: list[str] = []
        try:
            run_id = proc.stdout.readline().strip()
            assert run_id, "the crash-test run did not open"
            created.append(run_id)
            os.kill(proc.pid, signal.SIGKILL)                 # the unexpected death
            proc.wait()
            alive = uuid.uuid4()
            created.append(str(alive))
            async with engine.begin() as c:
                assert (await c.execute(text("select status from ingest_run where run_id = "
                    "cast(:r as uuid)"), {"r": run_id})).scalar() == "RUNNING"   # the orphan
                await c.execute(text("""
                    insert into ingest_run (run_id, source, stream, vendor_endpoint,
                      request_params, code_git_sha, config_sha256, argv, operator, mode,
                      status, authz_token_sha256, started_at, rows_written)
                    values (:r, 'UPSTOX_REST_V3', 'ohlcv.1m.crash-test', 't', cast(:p as jsonb),
                            't', :c, ARRAY['x'], 'pytest', 'COMMIT', 'RUNNING', :h, now(), 0)"""),
                    {"r": alive, "c": "c" * 64, "h": "a" * 64, "p": json.dumps(
                        {"runner": {"pid": os.getpid(), "host": HOST, "boot_id": boot_id()}})})
            async with async_sessionmaker(engine, expire_on_commit=False)() as s:
                rep = await reap_runs(s, commit=True, token=TOKEN)
            created.append(rep["run_id"])
            reaped = {o["run_id"] for o in rep["orphans"]}
            assert run_id in reaped and str(alive) not in reaped
            async with engine.begin() as c:
                row = (await c.execute(text("select status, error from ingest_run where "
                       "run_id = cast(:r as uuid)"), {"r": run_id})).one()
                live = (await c.execute(text("select status from ingest_run where "
                        "run_id = :r"), {"r": alive})).scalar()
            assert row.status == "ABORTED" and "is gone" in row.error
            assert live == "RUNNING"
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            async with engine.begin() as c:                  # leave the test DB as found
                await c.execute(text("delete from ingest_watermark where last_run_id = "
                                     "any(cast(:r as uuid[]))"), {"r": created})
                await c.execute(text("delete from ingest_run where run_id = "
                                     "any(cast(:r as uuid[]))"), {"r": created})
            await engine.dispose()


@pytest.mark.db
@pytest.mark.integration
class TestStatus:
    async def test_status_counts_every_state_and_never_shows_a_secret(self, db_session,
                                                                        tmp_path):
        from app.ops.status import snapshot
        s = db_session
        now = _dt.datetime.now(_dt.UTC)
        for status, err in (("COMPLETE", None), ("COMPLETE", None), ("FAILED", "x"),
                            ("ABORTED", "RateLimited"), ("ABORTED",
                             "reaped by maint.reap_runs: process 1 is gone"), ("RUNNING", None)):
            await s.execute(text("""
                insert into ingest_run (run_id, source, stream, vendor_endpoint, request_params,
                  code_git_sha, config_sha256, argv, operator, mode, status, authz_token_sha256,
                  started_at, finished_at, rows_written, error)
                values (:r, 'UPSTOX_REST_V3', 'ohlcv.1h.statustest', 't', '{}', 't', :c,
                        ARRAY['main.py', '--token', '<redacted>'], 'pytest', 'COMMIT', :st, :h,
                        :t, :f, 0, :e)"""),
                {"r": uuid.uuid4(), "c": "c" * 64, "h": "a" * 64, "st": status, "t": now,
                 "f": None if status == "RUNNING" else now, "e": err})
        (tmp_path / "var" / "run").mkdir(parents=True)
        (tmp_path / "var" / "logs" / "daily").mkdir(parents=True)
        snap = await snapshot(s, tmp_path)
        f = snap["families"]["candles_1h"]
        assert f["last_started"] is not None
        assert (f["complete_24h"], f["failed_24h"], f["aborted_24h"], f["reaped_24h"],
                f["running_now"]) >= (2, 1, 2, 1, 1)
        assert snap["candles_lock"] == "FREE" and snap["running"]["count"] >= 1
        doc = json.dumps(snap, default=str)
        assert TOKEN not in doc and "--token" not in doc
        from app.vendor.upstox.auth import load_cached
        rec = load_cached()
        if rec is not None:
            assert rec.access_token not in doc                # Upstox token never shown
