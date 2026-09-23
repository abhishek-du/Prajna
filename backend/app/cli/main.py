"""prajna — command line.

--dry-run is the DEFAULT for every ingestion command. Writing requires both
--commit and a valid write token (constraint #10). A flag alone is not
authorization.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys

import typer

from app.core.config import get_settings
from app.core.logging import configure, get_logger

app = typer.Typer(add_completion=False, help="AutoTrade Pro V2 (prajna) — Upstox-only ingestion")
db_app = typer.Typer(help="database / migrations")
ingest_app = typer.Typer(help="ingestion runs (dry-run by default)")
app.add_typer(db_app, name="db")
app.add_typer(ingest_app, name="ingest")


@app.callback()
def _root(
    log_level: str = typer.Option(None, help="override PRAJNA_LOG_LEVEL"),
    plain: bool = typer.Option(False, help="human-readable logs instead of JSON"),
):
    s = get_settings()
    configure(level=log_level or s.PRAJNA_LOG_LEVEL, json_output=not plain)


# ── db ──────────────────────────────────────────────────────────────────────
def _alembic(*args: str, dsn: str | None = None) -> int:
    cmd = [sys.executable, "-m", "alembic", "-c", "alembic.ini"]
    if dsn:
        cmd += ["-x", f"dsn={dsn}"]
    return subprocess.call([*cmd, *args])


@db_app.command("upgrade")
def db_upgrade(
    revision: str = typer.Argument("head"),
    test_db: bool = typer.Option(False, "--test-db", help="target PRAJNA_TEST_DATABASE_URL"),
):
    dsn = get_settings().PRAJNA_TEST_DATABASE_URL if test_db else None
    raise typer.Exit(_alembic("upgrade", revision, dsn=dsn))


@db_app.command("downgrade")
def db_downgrade(revision: str = typer.Argument(...)):
    raise typer.Exit(_alembic("downgrade", revision))


@db_app.command("current")
def db_current():
    raise typer.Exit(_alembic("current"))


@db_app.command("status")
def db_status():
    """Row counts and provenance coverage for every table."""
    from app.cli.status import print_status
    asyncio.run(print_status())


@db_app.command("sql")
def db_sql(
    statement: str = typer.Argument(..., help="SQL to run"),
    limit: int = typer.Option(100, help="max rows to print"),
    allow_write: bool = typer.Option(
        False, "--allow-write",
        help="open a writable transaction (default is READ ONLY, enforced by Postgres)",
    ),
):
    """Run ad-hoc SQL. Read-only unless --allow-write."""
    from app.cli.sql import main as run
    run(statement, allow_write, limit)


@db_app.command("tables")
def db_tables():
    """List tables with row counts and size."""
    from app.cli.sql import main as run
    run(
        """
        select c.relname as table,
               c.reltuples::bigint as est_rows,
               pg_size_pretty(pg_total_relation_size(c.oid)) as size
        from pg_class c join pg_namespace n on n.oid = c.relnamespace
        where c.relkind = 'r' and n.nspname = 'public'
        order by c.relname
        """,
        False, 200,
    )


@db_app.command("describe")
def db_describe(table: str = typer.Argument(...)):
    """Show columns, types and constraints for one table."""
    from app.cli.sql import main as run
    run(f"""
        select column_name, data_type, is_nullable, coalesce(column_default,'') as default
        from information_schema.columns
        where table_schema='public' and table_name='{table}'
        order by ordinal_position
    """, False, 200)


@db_app.command("web")
def db_web(
    port: int = typer.Option(8081, help="port (8080 is taken by another app on this host)"),
    host: str = typer.Option("127.0.0.1", help="bind address; loopback only by default"),
):
    """Read-only web browser for the database."""
    from app.web.viewer import serve
    serve(host=host, port=port)


@db_app.command("check-isolation")
def db_check_isolation():
    """Prove the configured DSN is not a V1 database."""
    from app.core.config import database_name
    from app.db.engine import assert_not_v1

    dsn = get_settings().PRAJNA_DATABASE_URL
    assert_not_v1(dsn)
    typer.echo(f"OK: target database is '{database_name(dsn)}' (not a V1 database)")


# ── ingest ──────────────────────────────────────────────────────────────────
@ingest_app.command("preopen")
def ingest_preopen(
    commit: bool = typer.Option(False, "--commit", help="write to the database"),
    token: str = typer.Option(None, "--token", help="write authorization token"),
    replay_from: str = typer.Option(None, "--replay-from-archive", help="re-parse one archive"),
    replay_session_manifest: str = typer.Option(
        None, "--replay-from-session", help="re-parse every archive of a capture session"),
    session_date: str = typer.Option(
        None, "--session-date", help="YYYY-MM-DD; defaults to the archive header's"),
):
    """Replay pre-open archives into the database (dry-run by default).

    Recording is `ingest preopen-capture`; this command turns archives into
    rows. A session (several connections) replays each archive as its own run.
    """
    import datetime as _dt
    import json as _json
    import pathlib

    log = get_logger("cli")
    if bool(replay_from) == bool(replay_session_manifest):
        log.error("choose_one", options="--replay-from-archive | --replay-from-session",
                  hint="recording is `ingest preopen-capture`")
        raise typer.Exit(2)

    from app.db.engine import get_sessionmaker
    from app.ingest.preopen import replay_archive, replay_session

    def _plain(report) -> dict:
        out = {k: getattr(report, k) for k in report.__slots__}
        out["rows_written"] = report.rows_written
        return out

    async def _go():
        async with get_sessionmaker()() as s:
            if replay_session_manifest:
                return await replay_session(s, pathlib.Path(replay_session_manifest),
                                            commit=commit, token=token)
            return await replay_archive(
                s, pathlib.Path(replay_from), commit=commit, token=token,
                session_date=_dt.date.fromisoformat(session_date) if session_date else None,
            )

    report = asyncio.run(_go())
    if replay_session_manifest:
        out = {"session_id": report.session_id, "session_date": report.session_date,
               "status": report.status, "rows_written": report.rows_written,
               "error": report.error, "shards": [_plain(r) for r in report.shards]}
    else:
        out = _plain(report)
    typer.echo(_json.dumps(out, indent=2, default=str))
    raise typer.Exit(0 if report.status == "COMPLETE" else 1)


@ingest_app.command("universe")
def ingest_universe(
    from_file: str = typer.Option(None, "--from-file", help="a local copy of NSE.json.gz"),
    payload_sha256: str = typer.Option(
        None, "--payload-sha256", help="re-select from a master already in raw_payload"),
    download: bool = typer.Option(
        False, "--download", help="fetch the public master from assets.upstox.com (no token)"),
    session_date: str = typer.Option(None, "--session-date", help="YYYY-MM-DD; default today IST"),
    cap: int = typer.Option(
        0, "--cap", help="cap the universe itself (0 = none; connection capacity is applied "
                         "at capture, not here)"),
    keys_out: str = typer.Option(None, "--keys-out", help="write the subscribed keys here"),
    commit: bool = typer.Option(False, "--commit", help="write to the database"),
    token: str = typer.Option(None, "--token", help="write authorization token"),
):
    """Select the pre-open universe from the Upstox instrument master.

    Exactly one source: --from-file, --payload-sha256, or --download. The
    master is archived before it is parsed. --keys-out feeds
    `ingest preopen-capture --keys-file`.
    """
    import datetime as _dt
    import json as _json
    import pathlib

    from app.core.clock import now, now_ist
    from app.db.engine import get_sessionmaker
    from app.ingest.universe import load_archived_master, select_universe
    from app.sources.upstox_instruments import MASTER_URL, download_master
    from app.storage.payload_store import PayloadStore

    log = get_logger("cli")
    if sum(bool(x) for x in (from_file, payload_sha256, download)) != 1:
        log.error("choose_one_source", options="--from-file | --payload-sha256 | --download")
        raise typer.Exit(2)
    day = _dt.date.fromisoformat(session_date) if session_date else now_ist().date()
    store = PayloadStore(get_settings().archive_dir)

    local_bytes, local_uri = b"", ""
    if from_file:
        p = pathlib.Path(from_file)
        local_bytes, local_uri = p.read_bytes(), f"file://{p.resolve()}"

    async def _go():
        async with get_sessionmaker()() as s:
            status, uri = None, MASTER_URL
            if download:
                d = await download_master()
                data, fetched, status, uri = d.data, d.fetched_at, d.http_status, d.url
            elif payload_sha256:
                data, fetched, status = await load_archived_master(s, payload_sha256)
            else:
                # We cannot know when a local copy was downloaded; now() is the
                # bound that can never be too early.
                data, fetched, uri = local_bytes, now(), local_uri
            return await select_universe(
                s, data, fetched_at=fetched, session_date=day, cap=cap or None,
                commit=commit, token=token, store=store, source_uri=uri, http_status=status,
            )

    report = asyncio.run(_go())
    if keys_out and report.status == "COMPLETE":
        lines = [
            f"# prajna pre-open universe {report.universe} for {report.session_date}",
            f"# run_id {report.run_id}  master_sha256 {report.master_sha256}",
            f"# rules {report.rules_version} {report.rules_sha256}",
            f"# cap {report.cap} (UNVERIFIED, B5)  subscribed {report.subscribed}"
            f"  sha256 {report.subscribed_sha256}",
            *report.subscribed_keys,
        ]
        pathlib.Path(keys_out).write_text("\n".join(lines) + "\n")
    out = report.public()
    out["cap_excluded"] = f"{len(report.cap_excluded)} keys (named in ingest_anomaly)"
    out["anomalies"] = [{k: a[k] for k in ("severity", "kind", "subject")}
                        for a in report.anomalies]
    typer.echo(_json.dumps(out, indent=2, default=str))
    raise typer.Exit(0 if report.status == "COMPLETE" else 1)


@ingest_app.command("preopen-capture")
def ingest_preopen_capture(
    keys_file: str = typer.Option(
        None, "--keys-file", help="instrument_keys, one per line (# comments ok)"),
    universe_date: str = typer.Option(
        None, "--universe-date", help="use the committed `preopen` universe for this date"),
    session_date: str = typer.Option(None, "--session-date", help="YYYY-MM-DD; default today IST"),
    until: str = typer.Option("09:20", "--until", help="stop at this IST wall time (HH:MM)"),
    mode: str = typer.Option("full", "--mode", help="wire subscribe mode (full -> full_d5)"),
    connections: int = typer.Option(
        2, "--connections", help="max concurrent connections (2 measured 2026-09-23)"),
    per_connection: int = typer.Option(
        2000, "--per-connection", help="keys per connection (2000 measured 2026-09-23)"),
    max_frames: int = typer.Option(
        None, "--max-frames", help="stop each connection after N frames (smoke test)"),
    stale_after: float = typer.Option(30.0, "--stale-after", help="seconds without data"),
):
    """Record the Upstox pre-open WebSocket feed. Writes archives, NO rows.

    The universe is split, in sorted order, into shards of <= --per-connection
    keys, one connection each. Uses the cached Upstox token only and never logs
    in by itself: an invalid token stops the capture (blocker B0). Replay with
    `ingest preopen --replay-from-session <manifest>`.
    """
    import datetime as _dt
    import hashlib
    import json as _json
    import pathlib
    import signal

    from sqlalchemy import select

    from app.contracts.identity import parse_instrument_key
    from app.contracts.universe import PREOPEN_UNIVERSE, plan_shards
    from app.core.clock import IST, ist_at, now, now_ist
    from app.db.engine import get_sessionmaker
    from app.db.models import InstrumentUniverseMembership as Member
    from app.sources.upstox_preopen_session import PreopenCaptureSession
    from app.sources.upstox_preopen_ws import RecorderConfig
    from app.vendor.upstox.auth import load_cached, probe
    from app.vendor.upstox.feed_auth import authorize_feed_v3

    log = get_logger("cli")
    if bool(keys_file) == bool(universe_date):
        log.error("choose_one_universe", options="--keys-file | --universe-date")
        raise typer.Exit(2)

    extra: dict = {}
    if keys_file:
        raw = pathlib.Path(keys_file).read_bytes()
        keys = [ln.split("#", 1)[0].strip() for ln in raw.decode().splitlines()]
        keys = [k for k in keys if k]
        extra = {"universe_source": "keys_file",
                 "keys_file": str(pathlib.Path(keys_file).resolve()),
                 "keys_file_sha256": hashlib.sha256(raw).hexdigest()}
    else:
        udate = _dt.date.fromisoformat(universe_date)

        async def _load():
            async with get_sessionmaker()() as s:
                return (await s.execute(
                    select(Member.instrument_key, Member.run_id, Member.payload_sha256)
                    .where(Member.universe == PREOPEN_UNIVERSE, Member.session_date == udate)
                    .order_by(Member.instrument_key))).all()
        rows = asyncio.run(_load())
        keys = [r.instrument_key for r in rows]
        extra = {"universe_source": "instrument_universe_membership",
                 "universe_date": universe_date,
                 "universe_run_ids": sorted({str(r.run_id) for r in rows}),
                 "instrument_master_sha256": sorted({r.payload_sha256 for r in rows})}
    for k in keys:
        parse_instrument_key(k)
    if not keys:
        log.error("empty_universe", **{k: v for k, v in extra.items() if isinstance(v, str)})
        raise typer.Exit(2)

    day = _dt.date.fromisoformat(session_date) if session_date else now_ist().date()
    hh, mm = (int(x) for x in until.split(":"))
    stop_at = ist_at(day, _dt.time(hh, mm))
    if stop_at <= now():
        log.error("window_already_over", until_ist=stop_at.astimezone(IST).isoformat())
        raise typer.Exit(2)

    rec = load_cached()
    ok, detail = probe(rec.access_token) if rec else (False, {"reason": "no cached token"})
    if not ok:
        log.error("upstox_token_invalid", blocker="B0",
                  action="refresh it with `prajna upstox login`; capture never logs in itself",
                  detail=str(detail)[:200])
        raise typer.Exit(3)
    extra["upstox_user_id"] = rec.user_id

    plan = plan_shards(keys, per_connection=per_connection, max_connections=connections)
    cfg = RecorderConfig(mode=mode, cap=per_connection, stale_after=stale_after)

    async def _go():
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
        cap_session = PreopenCaptureSession(
            get_settings().archive_dir, session_date=day, plan=plan,
            authorize=lambda: authorize_feed_v3(rec.access_token), config=cfg,
            stop_at=stop_at, max_frames_per_connection=max_frames, stop=stop,
            extra_header=extra,
        )
        typer.echo(f"session manifest: {cap_session.manifest_path}", err=True)
        return cap_session.manifest_path, await cap_session.run()

    manifest, doc = asyncio.run(_go())
    out = {"manifest": str(manifest), "status": doc["status"], "coverage": {
        k: v for k, v in (doc["coverage"] or {}).items() if k != "never_seen_keys"},
        "shards": [{"index": sh["index"], "keys": sh["keys"], "error": sh["error"],
                    "frames": (sh["summary"] or {}).get("frames"),
                    "reconnects": (sh["summary"] or {}).get("reconnects")}
                   for sh in doc["shards"]],
        "excluded_by_capacity": len(doc["universe"]["excluded_by_capacity"]),
        "next": f"ingest preopen --replay-from-session {manifest}"}
    typer.echo(_json.dumps(out, indent=2, default=str))
    raise typer.Exit(0 if doc["status"] == "complete" else 1)


upstox_app = typer.Typer(help="Upstox vendor operations")
app.add_typer(upstox_app, name="upstox")


@upstox_app.command("token-status")
def upstox_token_status():
    """Probe the cached token against /v2/user/profile. Never prints the token."""
    import json as _json

    from app.vendor.upstox.auth import token_status
    typer.echo(_json.dumps(token_status(), indent=2, default=str))


@upstox_app.command("login")
def upstox_login(
    force: bool = typer.Option(False, "--force", help="mint even if the cached token works"),
    insecure_tls: bool = typer.Option(
        False, "--insecure-tls",
        help="disable TLS verification (V1 did this unconditionally; V2 does not)",
    ),
):
    """Mint an Upstox access token via the TOTP flow. Performs a REAL login."""
    import json as _json

    from app.vendor.upstox.auth import ensure_access_token
    rec = ensure_access_token(force=force, verify_tls=not insecure_tls)
    typer.echo(_json.dumps({
        "ok": True,
        "user_id": rec.user_id,
        "email": rec.email,
        "token_length": len(rec.access_token),
        "minted_at": rec.minted_at.isoformat(),
        "cached_at": "backend/var/upstox_token.json (0600, gitignored)",
    }, indent=2))


if __name__ == "__main__":
    app()
