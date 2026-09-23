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
    replay_from: str = typer.Option(None, "--replay-from-archive", help="re-parse an archive"),
    session_date: str = typer.Option(
        None, "--session-date", help="YYYY-MM-DD; defaults to the archive header's"),
):
    """Replay a pre-open frame archive into the database (dry-run by default).

    Live capture (the WebSocket recorder) is not built yet; it needs a valid
    Upstox token (blocker B0).
    """
    import datetime as _dt
    import json as _json
    import pathlib

    log = get_logger("cli")
    if not replay_from:
        log.error("not_implemented", milestone="M1",
                  what="live WebSocket capture; only --replay-from-archive exists",
                  blocker="B0: live capture requires a valid Upstox token")
        raise typer.Exit(2)

    from app.db.engine import get_sessionmaker
    from app.ingest.preopen import replay_archive

    async def _go():
        async with get_sessionmaker()() as s:
            return await replay_archive(
                s, pathlib.Path(replay_from), commit=commit, token=token,
                session_date=_dt.date.fromisoformat(session_date) if session_date else None,
            )

    report = asyncio.run(_go())
    out = {k: getattr(report, k) for k in report.__slots__}
    out["rows_written"] = report.rows_written
    typer.echo(_json.dumps(out, indent=2, default=str))
    raise typer.Exit(0 if report.status == "COMPLETE" else 1)


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
