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


@db_app.command("redact-argv")
def db_redact_argv(
    commit: bool = typer.Option(False, "--commit", help="rewrite the rows (default: count)"),
    token: str = typer.Option(None, "--token", envvar="PRAJNA_SUPPLIED_TOKEN",
                              help="write authorization token (or env PRAJNA_SUPPLIED_TOKEN; prefer the env: argv is visible to ps)"),
):
    """Redact write tokens persisted in ingest_run.argv (idempotent; RUNNING
    rows are skipped until they finish)."""
    import json as _json

    from app.db.engine import get_sessionmaker
    from app.ingest.redact import redact_run_argv

    async def _go():
        async with get_sessionmaker()() as s:
            return await redact_run_argv(s, commit=commit, token=token)

    typer.echo(_json.dumps(asyncio.run(_go()), indent=2))


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
    token: str = typer.Option(None, "--token", envvar="PRAJNA_SUPPLIED_TOKEN",
                              help="write authorization token (or env PRAJNA_SUPPLIED_TOKEN; prefer the env: argv is visible to ps)"),
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


@ingest_app.command("calendar")
def ingest_calendar_cmd(
    date_from: str = typer.Option(..., "--from", help="YYYY-MM-DD"),
    date_to: str = typer.Option(..., "--to", help="YYYY-MM-DD (inclusive, <= 400 days)"),
    commit: bool = typer.Option(False, "--commit", help="write to the database"),
    token: str = typer.Option(None, "--token", envvar="PRAJNA_SUPPLIED_TOKEN",
                              help="write authorization token (or env PRAJNA_SUPPLIED_TOKEN; prefer the env: argv is visible to ps)"),
):
    """NSE trading sessions from Upstox /v2/market/holidays + /v2/market/timings.

    One timings call per date (hours are never assumed). Uses the cached Upstox
    token; an invalid token stops the run (blocker B0).
    """
    import datetime as _dt
    import json as _json

    from app.db.engine import get_sessionmaker
    from app.ingest.calendar import ingest_calendar
    from app.sources.upstox_calendar import UpstoxCalendarClient
    from app.storage.payload_store import PayloadStore
    from app.vendor.upstox.auth import load_cached

    log = get_logger("cli")
    rec = load_cached()
    if rec is None:
        log.error("upstox_token_missing", blocker="B0", action="run `prajna upstox login`")
        raise typer.Exit(3)

    async def _go():
        from sqlalchemy import text as _text

        from app.core.clock import now_ist
        client = UpstoxCalendarClient(rec.access_token)
        try:
            async with get_sessionmaker()() as s:
                # Past dates: session evidence = the NIFTY 50 daily bars already
                # stored (timings is a generic schedule for past dates).
                bars = set((await s.execute(_text(
                    "select session_date from ohlcv_bar where timeframe='1d' "
                    "and instrument_key='NSE_INDEX|Nifty 50'"))).scalars())
                # weekdays with NO NSE trading at all in Upstox data: no bar of any
                # of the 3 indices and zero NSE_EQ daily bars (one query, the range)
                closed = set((await s.execute(_text("""
                    select d::date from generate_series(cast(:a as date), cast(:b as date),
                                                        interval '1 day') d
                    where extract(isodow from d) < 6 and not exists (
                      select 1 from ohlcv_bar b join instrument i
                        on i.instrument_id = b.instrument_id
                      where b.timeframe = '1d' and b.session_date = d::date
                        and i.segment in ('NSE_EQ', 'NSE_INDEX'))"""),
                    {"a": _dt.date.fromisoformat(date_from),
                     "b": _dt.date.fromisoformat(date_to)})).scalars())
                return await ingest_calendar(
                    s, date_from=_dt.date.fromisoformat(date_from),
                    date_to=_dt.date.fromisoformat(date_to),
                    holidays=client.holidays, timings=client.timings,
                    store=PayloadStore(get_settings().archive_dir),
                    commit=commit, token=token, holiday_on=client.holiday_on,
                    past_before=now_ist().date(), index_bar_dates=bars,
                    market_closed_dates=closed,
                )
        finally:
            await client.aclose()

    report = asyncio.run(_go())
    out = report.public()
    out["sessions"] = [x for x in report.sessions if x["session_type"] != "NORMAL"]
    out["anomalies"] = [{k: a[k] for k in ("severity", "kind", "subject")} | {
        "reason": a["detail"].get("reason")} for a in report.anomalies]
    typer.echo(_json.dumps(out, indent=2, default=str))
    raise typer.Exit(0 if report.status == "COMPLETE" else 1)


@ingest_app.command("instruments")
def ingest_instruments(
    payload_sha256: str = typer.Option(
        ..., "--payload-sha256", help="sha256 of an ALREADY ARCHIVED instrument master"),
    commit: bool = typer.Option(False, "--commit", help="write to the database"),
    token: str = typer.Option(None, "--token", envvar="PRAJNA_SUPPLIED_TOKEN",
                              help="write authorization token (or env PRAJNA_SUPPLIED_TOKEN; prefer the env: argv is visible to ps)"),
):
    """M3.0: load CURRENT instrument rows from an archived Upstox master.

    Never downloads. Verifies the archived bytes against --payload-sha256
    before parsing. Identical rows are a no-op; a changed attribute fails.
    """
    import json as _json

    from app.db.engine import get_sessionmaker
    from app.ingest.instruments import load_current_instruments

    async def _go():
        async with get_sessionmaker()() as s:
            return await load_current_instruments(
                s, master_sha256=payload_sha256, archive_root=get_settings().archive_dir,
                commit=commit, token=token)

    report = asyncio.run(_go())
    out = report.public()
    out["anomalies"] = [{k: a[k] for k in ("severity", "kind", "subject")}
                        for a in report.anomalies]
    typer.echo(_json.dumps(out, indent=2, default=str))
    raise typer.Exit(0 if report.status == "COMPLETE" else 1)


@ingest_app.command("candles")
def ingest_candles(
    timeframe: list[str] = typer.Option(..., "--timeframe", help="repeatable: 1m 5m 15m 1h 1d"),
    date_from: str = typer.Option(None, "--from", help="YYYY-MM-DD (historical)"),
    date_to: str = typer.Option(None, "--to", help="YYYY-MM-DD (historical, inclusive)"),
    intraday: bool = typer.Option(False, "--intraday", help="today's bars (intraday endpoint)"),
    key: list[str] = typer.Option(None, "--key", help="repeatable instrument_key"),
    keys_file: str = typer.Option(None, "--keys-file", help="instrument_keys, one per line"),
    all_instruments: bool = typer.Option(
        False, "--all-instruments", help="every current NSE_EQ + NSE_INDEX instrument"),
    global_instruments: bool = typer.Option(
        False, "--global", help="every current GLOBAL_INDEX / GLOBAL_INDICATOR instrument "
                                "(daily only: their sessions are not on the NSE grid)"),
    commit: bool = typer.Option(False, "--commit", help="write to the database"),
    token: str = typer.Option(None, "--token", envvar="PRAJNA_SUPPLIED_TOKEN",
                              help="write authorization token (or env PRAJNA_SUPPLIED_TOKEN; prefer the env: argv is visible to ps)"),
    no_resume: bool = typer.Option(False, "--no-resume", help="ignore watermarks"),
):
    """Ingest Upstox candles into ohlcv_bar (dry-run by default). M4.3.

    Only COMPLETE bars are persisted. Every response is archived first.
    Timeframes and ranges are yours to choose (D1/D2 are not decided here).
    A rate limit stops the batch with every checkpoint intact.
    """
    import datetime as _dt
    import json as _json
    import pathlib

    from sqlalchemy import literal_column, select

    from app.db.engine import get_sessionmaker
    from app.db.models import Instrument
    from app.ingest.candles import CandleIngestor, CandleJob, plan_jobs
    from app.storage.payload_store import PayloadStore
    from app.vendor.upstox.auth import load_cached
    from app.vendor.upstox.rest import UpstoxRestClient

    log = get_logger("cli")
    if sum(bool(x) for x in (key, keys_file, all_instruments, global_instruments)) != 1:
        log.error("choose_one_key_source",
                  options="--key | --keys-file | --all-instruments | --global")
        raise typer.Exit(2)
    if global_instruments and set(timeframe) != {"1d"}:
        log.error("global_is_daily_only", reason="intraday grid checks use NSE sessions")
        raise typer.Exit(2)
    if intraday == bool(date_from or date_to) or (not intraday and not (date_from and date_to)):
        log.error("choose_range", options="--from/--to (historical) | --intraday")
        raise typer.Exit(2)
    rec = load_cached()
    if rec is None:
        log.error("upstox_token_missing", blocker="B0", action="run `prajna upstox login`")
        raise typer.Exit(3)

    keys: list[str] = list(key or [])
    if keys_file:
        keys = [ln.split("#", 1)[0].strip()
                for ln in pathlib.Path(keys_file).read_text().splitlines()]
        keys = [k for k in keys if k]

    async def _go():
        rest = UpstoxRestClient(rec.access_token)
        try:
            async with get_sessionmaker()() as s:
                ks = keys
                if all_instruments or global_instruments:
                    from app.contracts.identity import GLOBAL_SEGMENTS
                    segs = (sorted(GLOBAL_SEGMENTS) if global_instruments
                            else ["NSE_EQ", "NSE_INDEX"])
                    ks = list((await s.execute(select(Instrument.instrument_key).where(
                        Instrument.valid_to == literal_column("'infinity'::date"),
                        Instrument.lifecycle_status == "ACTIVE",
                        Instrument.segment.in_(segs))
                        .order_by(Instrument.instrument_key))).scalars())
                if intraday:
                    jobs, unavailable = [CandleJob(k, tf, None) for k in sorted(set(ks))
                                         for tf in timeframe], []
                else:
                    jobs, unavailable = plan_jobs(ks, timeframe,
                                                  _dt.date.fromisoformat(date_from),
                                                  _dt.date.fromisoformat(date_to))
                ing = CandleIngestor(s, rest, PayloadStore(get_settings().archive_dir),
                                     commit=commit, token=token)
                return await ing.run(jobs, resume=not no_resume), unavailable
        finally:
            await rest.aclose()

    rep, unavailable = asyncio.run(_go())
    out = rep.summary()
    out["before_availability"] = len(unavailable)
    out["failed"] = [{"key": r.job.instrument_key, "tf": r.job.timeframe,
                      "window": r.coverage and r.coverage["window"], "error": r.error}
                     for r in rep.results if r.status in ("FAILED", "ABORTED")][:50]
    out["coverage"] = {o: sum(1 for r in rep.results if r.coverage and
                              r.coverage["outcome"] == o)
                       for o in ("DATA", "EMPTY", "VENDOR_ERROR")}
    obs: dict[str, int] = {}
    for r in rep.results:                      # classified later observations (phase 6)
        for k, v in (r.observations or {}).items():
            obs[k] = obs.get(k, 0) + v
    out["observations"] = obs
    typer.echo(_json.dumps(out, indent=2, default=str))
    raise typer.Exit(0 if not rep.stopped and not rep.count("FAILED") else 1)


@ingest_app.command("institutional")
def ingest_institutional(
    side: list[str] = typer.Option(["FII", "DII"], "--side", help="repeatable: FII DII"),
    data_type: list[str] = typer.Option(
        None, "--data-type", help="repeatable, e.g. NSE_EQ|CASH; default: every type of the side"),
    start: str = typer.Option("2026-04-01", "--start",
                              help="YYYY-MM-DD; the vendor has nothing before 2026-04-01"),
    max_requests: int = typer.Option(20, "--max-requests", help="per series"),
    commit: bool = typer.Option(False, "--commit", help="write to the database"),
    token: str = typer.Option(None, "--token", envvar="PRAJNA_SUPPLIED_TOKEN",
                              help="write authorization token (or env PRAJNA_SUPPLIED_TOKEN; prefer the env: argv is visible to ps)"),
    no_resume: bool = typer.Option(False, "--no-resume", help="ignore watermarks"),
):
    """Ingest Upstox FII/DII activity (1D) into macro_observation (dry-run by default).

    Every response is archived first. Only dates before today (IST) are
    persisted; knowable_at = fetched_at (unverified). A changed value for a
    stored date FAILS (D3's current policy); nothing is overwritten.
    """
    import datetime as _dt
    import json as _json

    from app.db.engine import get_sessionmaker
    from app.ingest.institutional import InstitutionalIngestor
    from app.parsers.upstox_institutional import DATA_TYPES
    from app.storage.payload_store import PayloadStore
    from app.vendor.upstox.auth import load_cached
    from app.vendor.upstox.rest import UpstoxRestClient

    log = get_logger("cli")
    series = [(sd.upper(), t) for sd in side for t in (data_type or DATA_TYPES.get(sd.upper(), ()))]
    bad = [p for p in series if p[1] not in DATA_TYPES.get(p[0], ())]
    if not series or bad:
        log.error("unsupported_series", series=bad or series, supported=DATA_TYPES)
        raise typer.Exit(2)
    rec = load_cached()
    if rec is None:
        log.error("upstox_token_missing", blocker="B0", action="run `prajna upstox login`")
        raise typer.Exit(3)

    async def _go():
        rest = UpstoxRestClient(rec.access_token)
        try:
            async with get_sessionmaker()() as s:
                ing = InstitutionalIngestor(s, rest, PayloadStore(get_settings().archive_dir),
                                            commit=commit, token=token)
                return await ing.run(series, start=_dt.date.fromisoformat(start),
                                     resume=not no_resume, max_requests=max_requests)
        finally:
            await rest.aclose()

    rep = asyncio.run(_go())
    out = rep.summary()
    out["problems"] = [{"series": f"{r.side} {r.data_type}", "from": str(r.end),
                        "status": r.status, "error": r.error}
                       for r in rep.results if r.status != "COMPLETE"][:50]
    typer.echo(_json.dumps(out, indent=2, default=str))
    raise typer.Exit(0 if not out["problems"] else 1)


@ingest_app.command("news")
def ingest_news(
    key: list[str] = typer.Option(None, "--key", help="repeatable instrument_key; "
                                  "default: every current instrument"),
    commit: bool = typer.Option(False, "--commit", help="write to the database"),
    token: str = typer.Option(None, "--token", envvar="PRAJNA_SUPPLIED_TOKEN",
                              help="write authorization token (or env PRAJNA_SUPPLIED_TOKEN; prefer the env: argv is visible to ps)"),
):
    """Ingest Upstox news (/v2/news, last 7 days) into news_article + news_instrument.

    Batches of 30 keys, every page archived first. Articles are identified by
    (heading, published_time); a changed article is never overwritten (WARN).
    Run at least daily: the vendor serves only the last 7 days.
    """
    import json as _json

    from sqlalchemy import literal_column, select

    from app.db.engine import get_sessionmaker
    from app.db.models import Instrument
    from app.ingest.news import NewsIngestor
    from app.storage.payload_store import PayloadStore
    from app.vendor.upstox.auth import load_cached
    from app.vendor.upstox.rest import UpstoxRestClient

    log = get_logger("cli")
    rec = load_cached()
    if rec is None:
        log.error("upstox_token_missing", blocker="B0", action="run `prajna upstox login`")
        raise typer.Exit(3)

    async def _go():
        rest = UpstoxRestClient(rec.access_token)
        try:
            async with get_sessionmaker()() as s:
                ks = list(key or [])
                if not ks:
                    ks = list((await s.execute(select(Instrument.instrument_key).where(
                        Instrument.valid_to == literal_column("'infinity'::date"),
                        Instrument.lifecycle_status == "ACTIVE",
                        Instrument.segment == "NSE_EQ")
                        .order_by(Instrument.instrument_key))).scalars())
                ing = NewsIngestor(s, rest, PayloadStore(get_settings().archive_dir),
                                   commit=commit, token=token)
                return await ing.run(ks)
        finally:
            await rest.aclose()

    rep = asyncio.run(_go())
    out = rep.summary()
    out["problems"] = [{"keys": f"{r.keys[0]}..({len(r.keys)})", "status": r.status,
                        "error": r.error} for r in rep.results if r.status != "COMPLETE"][:50]
    typer.echo(_json.dumps(out, indent=2, default=str))
    raise typer.Exit(0 if not out["problems"] else 1)


@ingest_app.command("corporate-actions")
def ingest_corporate_actions(
    isin: list[str] = typer.Option(None, "--isin", help="repeatable ISIN; "
                                   "default: every current NSE_EQ instrument"),
    resume_hours: int = typer.Option(0, "--resume-hours", help="skip ISINs already swept by a "
                                     "COMPLETE, non-superseded commit run in the last N hours"),
    commit: bool = typer.Option(False, "--commit", help="write to the database"),
    token: str = typer.Option(None, "--token", envvar="PRAJNA_SUPPLIED_TOKEN",
                              help="write authorization token (or env PRAJNA_SUPPLIED_TOKEN; prefer the env: argv is visible to ps)"),
):
    """Ingest Upstox corporate actions (/v2/fundamentals/{ISIN}/corporate-actions).

    Dividends, bonus, splits, rights: what Upstox serves (about one year back).
    Announcement is a DATE (no time is invented); knowable_at = fetched_at.
    """
    import json as _json

    from sqlalchemy import literal_column, select

    from app.db.engine import get_sessionmaker
    from app.db.models import Instrument
    from app.ingest.corporate_actions import CorporateActionIngestor
    from app.storage.payload_store import PayloadStore
    from app.vendor.upstox.auth import load_cached
    from app.vendor.upstox.rest import UpstoxRestClient

    log = get_logger("cli")
    rec = load_cached()
    if rec is None:
        log.error("upstox_token_missing", blocker="B0", action="run `prajna upstox login`")
        raise typer.Exit(3)

    async def _go():
        rest = UpstoxRestClient(rec.access_token)
        try:
            async with get_sessionmaker()() as s:
                isins = list(isin or [])
                if not isins:
                    isins = [x for x in (await s.execute(select(Instrument.isin).where(
                        Instrument.valid_to == literal_column("'infinity'::date"),
                        Instrument.lifecycle_status == "ACTIVE",
                        Instrument.segment == "NSE_EQ"))).scalars() if x]
                if resume_hours:
                    from sqlalchemy import text as _t
                    done = set((await s.execute(_t(
                        "select distinct jsonb_array_elements_text(request_params->'isins') "
                        "from ingest_run where stream='corporate_action.isin' and mode='COMMIT' "
                        "and status='COMPLETE' and not request_params ? 'superseded' "
                        "and started_at > now() - make_interval(hours => :h)"),
                        {"h": resume_hours})).scalars())
                    isins = [i for i in isins if i not in done]
                ing = CorporateActionIngestor(s, rest, PayloadStore(get_settings().archive_dir),
                                              commit=commit, token=token)
                return await ing.run(isins)
        finally:
            await rest.aclose()

    rep = asyncio.run(_go())
    out = rep.summary()
    out["problems"] = [{"isins": f"{r.isins[0]}..({len(r.isins)})", "status": r.status,
                        "error": r.error} for r in rep.results if r.status != "COMPLETE"][:50]
    typer.echo(_json.dumps(out, indent=2, default=str))
    raise typer.Exit(0 if not out["problems"] else 1)


@ingest_app.command("fundamentals")
def ingest_fundamentals(
    isin: list[str] = typer.Option(None, "--isin", help="repeatable ISIN; "
                                   "default: every current NSE_EQ instrument"),
    commit: bool = typer.Option(False, "--commit", help="write to the database"),
    token: str = typer.Option(None, "--token", envvar="PRAJNA_SUPPLIED_TOKEN",
                              help="write authorization token (or env PRAJNA_SUPPLIED_TOKEN; prefer the env: argv is visible to ps)"),
):
    """Ingest Upstox fundamentals (12 variants per ISIN) into fundamental_snapshot.

    profile, key ratios, shareholding, competitors, balance sheet / cash flow
    (consolidated + standalone) and income statement (x yearly/quarterly), each
    kept as sent. A new snapshot is stored only when the content changed.
    """
    import json as _json

    from sqlalchemy import literal_column, select

    from app.db.engine import get_sessionmaker
    from app.db.models import Instrument
    from app.ingest.fundamentals import FundamentalsIngestor
    from app.storage.payload_store import PayloadStore
    from app.vendor.upstox.auth import load_cached
    from app.vendor.upstox.rest import UpstoxRestClient

    log = get_logger("cli")
    rec = load_cached()
    if rec is None:
        log.error("upstox_token_missing", blocker="B0", action="run `prajna upstox login`")
        raise typer.Exit(3)

    async def _go():
        rest = UpstoxRestClient(rec.access_token)
        try:
            async with get_sessionmaker()() as s:
                isins = list(isin or [])
                if not isins:
                    isins = [x for x in (await s.execute(select(Instrument.isin).where(
                        Instrument.valid_to == literal_column("'infinity'::date"),
                        Instrument.lifecycle_status == "ACTIVE",
                        Instrument.segment == "NSE_EQ"))).scalars() if x]
                ing = FundamentalsIngestor(s, rest, PayloadStore(get_settings().archive_dir),
                                           commit=commit, token=token)
                return await ing.run(isins)
        finally:
            await rest.aclose()

    rep = asyncio.run(_go())
    out = rep.summary()
    out["problems"] = [{"isins": f"{r.isins[0]}..({len(r.isins)})", "status": r.status,
                        "error": r.error} for r in rep.results if r.status != "COMPLETE"][:50]
    typer.echo(_json.dumps(out, indent=2, default=str))
    raise typer.Exit(0 if not out["problems"] else 1)


@ingest_app.command("instruments-refresh")
def ingest_instruments_refresh(
    download: bool = typer.Option(False, "--download",
                                  help="fetch the public master from assets.upstox.com"),
    payload_sha256: str = typer.Option(None, "--payload-sha256",
                                       help="an instrument master already in raw_payload"),
    from_file: str = typer.Option(None, "--from-file", help="a local NSE.json.gz (tests, replay)"),
    commit: bool = typer.Option(False, "--commit", help="write to the database"),
    token: str = typer.Option(None, "--token", envvar="PRAJNA_SUPPLIED_TOKEN",
                              help="write authorization token (or env PRAJNA_SUPPLIED_TOKEN)"),
):
    """Daily instrument-master refresh: new listings, attribute versions and the
    listing lifecycle (ACTIVE / INELIGIBLE / REMOVED_FROM_MASTER / VENDOR_REJECTED).

    Archives the master first; never deletes; refuses a master that selects
    fewer than 95 % of the listed instruments. Exit 0 only when COMPLETE.
    """
    import json as _json
    import pathlib

    from app.core.clock import now
    from app.db.engine import get_sessionmaker
    from app.ingest.instrument_refresh import refresh_instruments
    from app.ingest.universe import load_archived_master
    from app.sources.upstox_instruments import MASTER_URL, download_master
    from app.storage.payload_store import PayloadStore

    log = get_logger("cli")
    if sum(bool(x) for x in (download, payload_sha256, from_file)) != 1:
        log.error("choose_one_source", options="--download | --payload-sha256 | --from-file")
        raise typer.Exit(2)
    store = PayloadStore(get_settings().archive_dir)

    async def _go():
        async with get_sessionmaker()() as s:
            status, uri = None, MASTER_URL
            if download:
                d = await download_master()
                data, fetched, status, uri = d.data, d.fetched_at, d.http_status, d.url
            elif payload_sha256:
                data, fetched, status = await load_archived_master(s, payload_sha256)
            else:
                pth = pathlib.Path(from_file)
                # when a local copy was downloaded is unknown: now() is never too early
                data, fetched, uri = pth.read_bytes(), now(), f"file://{pth.resolve()}"
            return await refresh_instruments(s, data, fetched_at=fetched, commit=commit,
                                             token=token, store=store, http_status=status,
                                             source_uri=uri)

    rep = asyncio.run(_go())
    typer.echo(_json.dumps(rep.public(), indent=2, default=str))
    raise typer.Exit(0 if rep.status == "COMPLETE" else 1)


@ingest_app.command("instruments-global")
def ingest_instruments_global(
    payload_sha256: str = typer.Option(None, "--payload-sha256",
                                       help="use an already archived global.json.gz"),
    commit: bool = typer.Option(False, "--commit", help="write to the database"),
    token: str = typer.Option(None, "--token", envvar="PRAJNA_SUPPLIED_TOKEN",
                              help="write authorization token (or env PRAJNA_SUPPLIED_TOKEN; prefer the env: argv is visible to ps)"),
):
    """Load Upstox's global instruments (S&P, Dow, USD/INR, Brent, ...) into instrument.

    Downloads the public global.json.gz (no token) and archives it first,
    unless --payload-sha256 names an archived copy.
    """
    import json as _json
    import pathlib

    import httpx

    from app.core.clock import now
    from app.db.engine import get_sessionmaker
    from app.ingest.global_instruments import GLOBAL_URL, load_global_instruments
    from app.ingest.instruments import locate_archived, resolve_fetched_at
    from app.storage.payload_store import PayloadStore, StoredPayload

    store = PayloadStore(get_settings().archive_dir)

    async def _go():
        async with get_sessionmaker()() as s:
            if payload_sha256:
                path = locate_archived(pathlib.Path(get_settings().archive_dir), payload_sha256)
                fetched, _ = await resolve_fetched_at(s, payload_sha256, path)
                data = PayloadStore.read(path, payload_sha256)
                stored = StoredPayload(payload_sha256, path, len(data), "application/gzip",
                                       fetched, None, True)
            else:
                async with httpx.AsyncClient(timeout=60, follow_redirects=True) as c:
                    r = await c.get(GLOBAL_URL)
                    fetched = now()
                r.raise_for_status()
                stored = store.put(r.content, source="UPSTOX_ASSETS",
                                   content_type="application/gzip", ext="json.gz",
                                   fetched_at=fetched)
            return await load_global_instruments(s, stored, commit=commit, token=token)

    rep = asyncio.run(_go())
    typer.echo(_json.dumps({"status": rep.status, "committed": rep.committed,
                            "payload_sha256": rep.payload_sha256, "rows": rep.rows_in_file,
                            "inserted": rep.inserted, "already_current": rep.already_current,
                            "keys": rep.keys, "error": rep.error}, indent=2))
    raise typer.Exit(0 if rep.status == "COMPLETE" else 1)


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
    token: str = typer.Option(None, "--token", envvar="PRAJNA_SUPPLIED_TOKEN",
                              help="write authorization token (or env PRAJNA_SUPPLIED_TOKEN; prefer the env: argv is visible to ps)"),
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


acceptance_app = typer.Typer(help="acceptance evidence (read-only)")
app.add_typer(acceptance_app, name="acceptance")


@acceptance_app.command("stage1")
def acceptance_stage1(
    out: str = typer.Option(None, "--out", help="JSON report (default: backend/var/acceptance/"
                            "stage1.json, whatever the working directory)"),
    md: str = typer.Option(None, "--md", help="regenerate the acceptance document here "
                           "(default: docs/STAGE_1_FINAL_ACCEPTANCE.md; '' = no)"),
):
    """Stage-1 final gate: criteria A-Y from the REAL database. Read-only.

    Exit 0 only when the overall verdict is COMPLETE. The gate's inputs and the
    default outputs are anchored to the project, never to the working directory;
    an explicit --out / --md is taken as given (relative to where you run it).
    """
    import json as _json
    import pathlib

    from app.acceptance.stage1 import anchored, evaluate, to_markdown
    from app.db.engine import get_sessionmaker

    out = out or str(anchored("var/acceptance/stage1.json"))
    md = str(anchored("../docs/STAGE_1_FINAL_ACCEPTANCE.md").resolve()) if md is None else md

    async def _go():
        async with get_sessionmaker()() as s:
            return await evaluate(s)

    rep = asyncio.run(_go())
    pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(out).write_text(_json.dumps(rep, indent=2, default=str))
    if md:
        pathlib.Path(md).write_text(to_markdown(rep))
    for c in rep["criteria"]:
        typer.echo(f"{c['id']}  {c['status']:13} {c['name']}"
                   + (f"   [decision {', '.join(c['decisions'])}]" if c["decisions"] else ""))
    typer.echo(f"OVERALL: {rep['overall']}")
    raise typer.Exit(0 if rep["overall"] == "COMPLETE" else 1)


@acceptance_app.command("preopen")
def acceptance_preopen(
    session_manifest: str = typer.Option(..., "--session", help="<stem>.session.json"),
    out: str = typer.Option(None, "--out", help="also write the JSON report here"),
):
    """Grade one real trading day's pre-open capture, end to end. Read-only.

    Replay the session with --commit first. B7/B8 are only graded from
    production-feed data whose ticks fall inside the pre-open window.
    """
    import json as _json
    import pathlib

    from app.acceptance.preopen_day import evaluate
    from app.db.engine import get_sessionmaker

    async def _go():
        async with get_sessionmaker()() as s:
            return await evaluate(s, pathlib.Path(session_manifest))

    doc = asyncio.run(_go()).as_dict()
    body = _json.dumps(doc, indent=2, default=str)
    if out:
        pathlib.Path(out).write_text(body + "\n")
    typer.echo(body)
    raise typer.Exit(0 if doc["verdict"] in ("PASS", "WARN") else 1)


@acceptance_app.command("instruments")
def acceptance_instruments(
    payload_sha256: str = typer.Option(..., "--payload-sha256", help="the loaded master"),
    out: str = typer.Option(None, "--out", help="also write the JSON report here"),
):
    """M3.0: archived master -> sha -> parse -> selection -> provenance ->
    instrument table -> replay (DRY_RUN) -> no changes."""
    import json as _json
    import pathlib

    from app.acceptance.instruments import evaluate
    from app.db.engine import get_sessionmaker

    async def _go():
        async with get_sessionmaker()() as s:
            return await evaluate(s, master_sha256=payload_sha256,
                                  archive_root=get_settings().archive_dir)

    doc = asyncio.run(_go())
    body = _json.dumps(doc, indent=2, default=str)
    if out:
        pathlib.Path(out).write_text(body + "\n")
    typer.echo(body)
    raise typer.Exit(0 if doc["verdict"] == "PASS" else 1)


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




# ── Stage 2 ──────────────────────────────────────────────────────────────────
derive_app = typer.Typer(help="derived Stage 1 records (no vendor calls)")
app.add_typer(derive_app, name="derive")


def _derive(fn_name: str, commit: bool, token: str | None):
    import json as _json

    from app.db.engine import get_sessionmaker
    from app.ingest import ca_derive

    async def _go():
        async with get_sessionmaker()() as s:
            return await getattr(ca_derive, fn_name)(s, commit=commit, token=token)

    typer.echo(_json.dumps(asyncio.run(_go()), indent=2, default=str))


@derive_app.command("global-contracts")
def derive_global_contracts_cmd(
    commit: bool = typer.Option(False, "--commit"),
    token: str = typer.Option(None, "--token", envvar="PRAJNA_SUPPLIED_TOKEN",
                              help="write authorization token (or env PRAJNA_SUPPLIED_TOKEN)"),
):
    """Measure each global instrument's label semantics, gaps, placeholders and
    revisions from its own stored series (no calendar assumed)."""
    import json as _json

    from app.db.engine import get_sessionmaker
    from app.ingest.global_contract import derive_global_contracts

    async def _go():
        async with get_sessionmaker()() as s:
            return await derive_global_contracts(s, commit=commit, token=token)

    typer.echo(_json.dumps(asyncio.run(_go()), indent=2, default=str))


@derive_app.command("price-basis")
def derive_price_basis_cmd(
    commit: bool = typer.Option(False, "--commit"),
    token: str = typer.Option(None, "--token", envvar="PRAJNA_SUPPLIED_TOKEN",
                              help="write authorization token (or env PRAJNA_SUPPLIED_TOKEN)"),
):
    """Give every candle payload without one its price basis (RAW_OBSERVED /
    VENDOR_ADJUSTED). Idempotent."""
    _derive("derive_price_basis", commit, token)


@derive_app.command("ca-factors")
def derive_ca_factors_cmd(
    commit: bool = typer.Option(False, "--commit"),
    token: str = typer.Option(None, "--token", envvar="PRAJNA_SUPPLIED_TOKEN",
                              help="write authorization token (or env PRAJNA_SUPPLIED_TOKEN)"),
):
    """Derive the adjustment factor of every corporate action (versioned), and
    whether the vendor's stored history is adjusted for it (with evidence)."""
    _derive("derive_ca_factors", commit, token)


ops_app = typer.Typer(help="operations: status, maintenance (no vendor calls)")
app.add_typer(ops_app, name="ops")


@ops_app.command("reap-runs")
def ops_reap_runs(
    commit: bool = typer.Option(False, "--commit", help="mark orphaned RUNNING runs ABORTED"),
    token: str = typer.Option(None, "--token", envvar="PRAJNA_SUPPLIED_TOKEN",
                              help="write authorization token (or env PRAJNA_SUPPLIED_TOKEN)"),
):
    """Mark RUNNING runs whose process is provably gone (pid dead, machine
    rebooted, or no identity and > 48 h old) ABORTED, with the reason."""
    import json as _json

    from app.db.engine import get_sessionmaker
    from app.ops.reaper import reap_runs

    async def _go():
        async with get_sessionmaker()() as s:
            return await reap_runs(s, commit=commit, token=token)

    typer.echo(_json.dumps(asyncio.run(_go()), indent=2, default=str))


@ops_app.command("status")
def ops_status(write: bool = typer.Option(False, "--write",
                                          help="also save var/status/ops_status_<stamp>.json")):
    """Operational snapshot: last run per job family, RUNNING runs, candles
    lock, token age, disk, recent runbook markers. Read-only."""
    import json as _json
    import pathlib

    from app.core.clock import now_ist
    from app.db.engine import get_sessionmaker
    from app.ops.status import snapshot

    base = pathlib.Path(__file__).resolve().parents[2]

    async def _go():
        async with get_sessionmaker()() as s:
            return await snapshot(s, base)

    snap = asyncio.run(_go())
    doc = _json.dumps(snap, indent=2, default=str)
    if write:
        out = base / "var" / "status" / f"ops_status_{now_ist():%Y%m%dT%H%M}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(doc)
    typer.echo(doc)


@ops_app.command("warmup-plan")
def ops_warmup_plan(
    sessions: int = typer.Option(..., "--sessions", help="completed sessions the feature needs"),
    timeframe: list[str] = typer.Option(..., "--timeframe", help="repeatable: 1m 15m 1h"),
    fraction: float = typer.Option(0.5, "--fraction", help="share of the per-user quota"),
):
    """Plan a TARGETED warm-up (N sessions, ACTIVE instruments lacking them):
    window, request windows, cost. Read-only; no vendor calls. The deferred
    full historical backfill is never planned here."""
    import json as _json

    from app.db.engine import get_sessionmaker
    from app.ops.warmup import plan

    async def _go():
        async with get_sessionmaker()() as s:
            return await plan(s, sessions=sessions, timeframes=timeframe, fraction=fraction)

    typer.echo(_json.dumps(asyncio.run(_go()), indent=2, default=str))


classify_app = typer.Typer(help="derived classifications (no vendor calls)")
app.add_typer(classify_app, name="classify")


@classify_app.command("securities")
def classify_securities_cmd(
    commit: bool = typer.Option(False, "--commit", help="write instrument_security_class"),
    token: str = typer.Option(None, "--token", envvar="PRAJNA_SUPPLIED_TOKEN",
                              help="write authorization token (or env PRAJNA_SUPPLIED_TOKEN)"),
):
    """Classify every current instrument as STOCK / FUND_UNIT / RIGHTS_ENTITLEMENT
    / OTHER from >= 2 independent signals; disagreement is REVIEW, too little
    evidence UNCLASSIFIED. Exit 0 when COMPLETE (REVIEW items are reported)."""
    import json as _json

    from app.db.engine import get_sessionmaker
    from app.ingest.security_class import classify_securities

    async def _go():
        async with get_sessionmaker()() as s:
            return await classify_securities(s, commit=commit, token=token)

    typer.echo(_json.dumps(asyncio.run(_go()), indent=2, default=str))


stage2_app = typer.Typer(help="Stage 2 data processing (derived from Stage 1; no vendor calls)")
app.add_typer(stage2_app, name="stage2")


@stage2_app.command("process")
def stage2_process(
    commit: bool = typer.Option(False, "--commit", help="write canon_* tables"),
    token: str = typer.Option(None, "--token", envvar="PRAJNA_SUPPLIED_TOKEN",
                              help="write authorization token (or env PRAJNA_SUPPLIED_TOKEN; prefer the env: argv is visible to ps)"),
    full: bool = typer.Option(False, "--full", help="recompute every pair (not incremental)"),
    live: bool = typer.Option(False, "--live", help="continuous mode (needs "
                              "STAGE2_LIVE_ENABLED=true; not approved)"),
):
    """Stage 1 tables -> canon_instrument + canon_coverage. Incremental, idempotent."""
    import json as _json

    from app.canon.process import process
    from app.db.engine import get_sessionmaker

    if live and not get_settings().STAGE2_LIVE_ENABLED:
        get_logger("cli").error("stage2_live_disabled",
                                reason="STAGE2_LIVE_ENABLED is false (not approved)")
        raise typer.Exit(2)

    async def _go():
        async with get_sessionmaker()() as s:
            return await process(s, commit=commit, token=token, full=full)

    rep = asyncio.run(_go())
    typer.echo(_json.dumps(rep.summary(), indent=2, default=str))
    raise typer.Exit(0 if rep.status == "COMPLETE" else 1)


@stage2_app.command("quality")
def stage2_quality(out: str = typer.Option(None, "--out", help="also write the JSON here")):
    """Stage 2 data-quality gates over the canonical layer. Read-only."""
    import json as _json
    import pathlib

    from app.canon.quality import run_gates
    from app.db.engine import get_sessionmaker

    async def _go():
        async with get_sessionmaker()() as s:
            return await run_gates(s)

    rep = asyncio.run(_go())
    if out:
        pathlib.Path(out).write_text(_json.dumps(rep, indent=2, default=str))
    for g in rep["gates"]:
        typer.echo(f"{g['status']:5} {g['count']:>8}  {g['gate']}"
                   + (f"   -> {g['diagnostic']}" if g["diagnostic"] else ""))
    typer.echo(f"QUALITY: {rep['status']}  {rep['informational']}")
    raise typer.Exit(0 if rep["status"] == "PASS" else 1)



@acceptance_app.command("stage2")
def acceptance_stage2(
    run_tests: bool = typer.Option(False, "--run-tests", help="also run the full test suite"),
    out: str = typer.Option(None, "--out", help="JSON report (default: backend/var/acceptance/"
                            "stage2.json, whatever the working directory)"),
    md: str = typer.Option(None, "--md", help="regenerate the acceptance document here "
                           "(default: docs/STAGE_2_ACCEPTANCE.md; '' = no)"),
    seed: int = typer.Option(None, "--seed", help="reproduce the E/O samples of a report"),
):
    """Stage 2 gate: criteria A-P from the real database (+ the test suite)."""
    import json as _json
    import pathlib

    from sqlalchemy import text as _t

    from app.acceptance import stage2 as S2
    from app.acceptance.stage1 import anchored
    from app.db.engine import get_sessionmaker

    out = out or str(anchored("var/acceptance/stage2.json"))
    md = str(anchored("../docs/STAGE_2_ACCEPTANCE.md").resolve()) if md is None else md

    tests = S2.run_tests() if run_tests else None

    async def _go():
        async with get_sessionmaker()() as s:
            rep = await S2.evaluate(s, tests, seed=seed)
            dep = dict((await s.execute(_t("""
                select timeframe || ' ' || state, sum(sessions) from canon_coverage
                where state = 'PENDING_BACKFILL' group by 1 order by 1"""))).all())
            return rep, {**{k: f"{int(v):,} sessions pending" for k, v in dep.items()},
                         "sector": "grows with the fundamentals sweep (Stage 1 criterion D/O)"}

    rep, dep = asyncio.run(_go())
    pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(out).write_text(_json.dumps(rep, indent=2, default=str))
    if md:
        pathlib.Path(md).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(md).write_text(S2.to_markdown(rep, dep))
    for c in rep["criteria"]:
        typer.echo(f"{c['id']}  {c['status']:8} {c['question']}")
    typer.echo(f"STAGE 2: {rep['overall']}")
    raise typer.Exit(0 if rep["overall"] == "PASS" else 1)


stage3_app = typer.Typer(help="Stage 3 feature engineering (reads the Stage 2 PIT API only; no "
                              "vendor calls; writes LOCKED)")
app.add_typer(stage3_app, name="stage3")


def _date(v: str):
    import datetime as _dt
    return _dt.date.fromisoformat(v)


def _lock_lines(conditions) -> None:
    for c in conditions:
        typer.echo(f"{'PASS' if c['ok'] else 'FAIL':5} {c['name']:20} {c['detail']}")


@stage3_app.command("registry")
def stage3_registry(as_json: bool = typer.Option(False, "--json")):
    """The feature registry and the diagram coverage (no database)."""
    import json as _json

    from app.features import registry as R

    if as_json:
        typer.echo(_json.dumps({"summary": R.summary(), "registry": R.registry_document()},
                               indent=2, default=str))
        return
    for f in R.FEATURES:
        typer.echo(f"{f.group:17} {f.id:28} {f.status:12} {f.param_status:9} "
                   f"{','.join(f.snapshots)}")
    typer.echo("")
    for d in R.DIAGRAM:
        typer.echo(f"{R.diagram_status(d):12} {d['group']:17} {d['item']}")
    typer.echo(_json.dumps(R.summary(), default=str))


@stage3_app.command("locks")
def stage3_locks(
    mode: str = typer.Option("RUN", "--mode", help="RUN | BACKFILL"),
    token: str = typer.Option(None, "--token", envvar="PRAJNA_SUPPLIED_TOKEN",
                              help="write token (prefer env PRAJNA_SUPPLIED_TOKEN)"),
):
    """Every execution-lock condition, PASS/FAIL. Read-only (records nothing)."""
    from app.db.engine import get_sessionmaker
    from app.features import locks

    async def _go():
        async with get_sessionmaker()() as s:
            return await locks.check(s, mode=mode.upper(), token=token)

    rep = asyncio.run(_go())
    _lock_lines(rep.conditions)
    typer.echo(f"STAGE 3 {rep.mode}: {'UNLOCKED' if rep.ok else 'LOCKED'}")
    raise typer.Exit(0 if rep.ok else 1)


@stage3_app.command("compute")
def stage3_compute(
    session: str = typer.Option(..., "--session", help="trading session date YYYY-MM-DD"),
    snapshot: str = typer.Option("PRE_SESSION", "--snapshot", help="PRE_SESSION | PRE_OPEN"),
    key: list[str] = typer.Option(None, "--key", help="instrument key (repeatable)"),
    symbol: list[str] = typer.Option(None, "--symbol", help="NSE_EQ trading symbol (repeatable)"),
    sample: int = typer.Option(0, "--sample", help="N deterministic canonical NSE_EQ instruments"),
    context: bool = typer.Option(True, "--context/--no-context", help="market-context features"),
    out: str = typer.Option(None, "--out", help="also write every row as JSON here"),
    show: bool = typer.Option(True, "--show/--no-show", help="print each row"),
):
    """DRY-RUN: compute the features at a snapshot and print them. Read-only
    transaction; writes nothing, needs no lock and no token."""
    import dataclasses
    import json as _json
    import pathlib

    from sqlalchemy import text as _t

    from app.db.engine import get_sessionmaker
    from app.features import engine as E
    from app.features import snapshots as SN

    async def _go():
        async with get_sessionmaker()() as s:
            await E.consistent_read(s, read_only=True)    # the run's isolation, never a write
            keys = list(key or [])
            for sym in symbol or []:
                k = (await s.execute(_t("""select instrument_key from canon_instrument
                    where segment = 'NSE_EQ' and trading_symbol = :t"""), {"t": sym})).scalar()
                if k is None:
                    raise typer.BadParameter(f"unknown NSE_EQ symbol {sym}")
                keys.append(k)
            if sample:
                keys += list((await s.execute(_t("""select instrument_key from canon_instrument
                    where included and lifecycle_status = 'ACTIVE' and segment = 'NSE_EQ'
                    order by md5(instrument_key) limit :n"""), {"n": sample})).scalars())
            snap = await SN.resolve(s, _date(session), snapshot.upper())
            res = await E.compute_snapshot(s, snap, list(dict.fromkeys(keys)),
                                           with_context=context)
            await s.rollback()
            return res

    res = asyncio.run(_go())
    if show:
        for r in res.rows:
            val = r.reason if r.value is None else f"{r.value:.12g}"
            typer.echo(f"{r.instrument_key:34} {r.feature_id:28} {val}")
    stats = {"mode": "DRY_RUN (read-only transaction; nothing written)",
             "session": str(res.snapshot.session_date), "snapshot": res.snapshot.kind,
             "as_of": res.snapshot.as_of.isoformat(), **res.stats()}
    if out:
        pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(out).write_text(_json.dumps(
            {**stats, "rows": [dataclasses.asdict(r) for r in res.rows]}, indent=2, default=str))
    typer.echo(_json.dumps(stats, indent=2, default=str))


def _stage3_commit(mode: str, sessions, snapshots: list[str], keys: list[str] | None,
                   token: str | None) -> None:
    """The locked write path shared by run/backfill: refused (exit 3) unless every
    lock condition holds; the refusal is audited in stage3_event."""
    import json as _json

    from app.db.engine import get_sessionmaker
    from app.features import engine as E
    from app.features import locks
    from app.features import snapshots as SN

    async def _go():
        async with get_sessionmaker()() as s:
            await locks.require(s, mode=mode, token=token, operator="cli")
            days = await sessions(s) if callable(sessions) else sessions
            out = []
            for d in days:
                for k in snapshots:
                    try:
                        snap = await SN.resolve(s, d, k)
                    except SN.NoSnapshot as e:
                        out.append({"session": str(d), "snapshot": k, "skipped": str(e)})
                        continue
                    out.append(await E.run_snapshot(s, snap, keys=keys, mode=mode, token=token))
            return out

    try:
        rep = asyncio.run(_go())
    except locks.LockRefused as e:
        _lock_lines(e.report.conditions)
        typer.echo(f"REFUSED: Stage 3 {mode} is locked (audited in stage3_event); nothing written")
        raise typer.Exit(3)
    typer.echo(_json.dumps(rep, indent=2, default=str))


@stage3_app.command("run")
def stage3_run(
    session: str = typer.Option(..., "--session"),
    snapshot: str = typer.Option("BOTH", "--snapshot", help="PRE_SESSION | PRE_OPEN | BOTH"),
    key: list[str] = typer.Option(None, "--key", help="restrict to these keys (default: universe)"),
    commit: bool = typer.Option(False, "--commit", help="required: write feature_value (LOCKED)"),
    token: str = typer.Option(None, "--token", envvar="PRAJNA_SUPPLIED_TOKEN"),
):
    """PRODUCTION: compute and store one session's features. LOCKED: refused unless
    every condition of `prajna stage3 locks` holds."""
    if not commit:
        typer.echo("stage3 run writes: pass --commit (lock-checked). "
                   "Read-only preview: prajna stage3 compute")
        raise typer.Exit(2)
    snaps = ["PRE_SESSION", "PRE_OPEN"] if snapshot.upper() == "BOTH" else [snapshot.upper()]
    _stage3_commit("RUN", [_date(session)], snaps, list(key) if key else None, token)


@stage3_app.command("backfill")
def stage3_backfill(
    start: str = typer.Option(..., "--from"),
    end: str = typer.Option(..., "--to"),
    commit: bool = typer.Option(False, "--commit", help="required (LOCKED)"),
    token: str = typer.Option(None, "--token", envvar="PRAJNA_SUPPLIED_TOKEN"),
):
    """PRODUCTION feature backfill over past sessions. LOCKED: every RUN condition
    plus PRAJNA_STAGE3_BACKFILL_ENABLED. Never runs the Stage 1 (vendor) backfill."""
    if not commit:
        typer.echo("stage3 backfill writes: pass --commit (lock-checked)")
        raise typer.Exit(2)
    from app.features import snapshots as SN

    async def _sessions(s):                  # resolved only AFTER the lock check passed
        return await SN.sessions_between(s, _date(start), _date(end))

    _stage3_commit("BACKFILL", _sessions, ["PRE_SESSION", "PRE_OPEN"], None, token)


@stage3_app.command("kill")
def stage3_kill(
    state: str = typer.Argument(..., help="on | off"),
    reason: str = typer.Option("", "--reason"),
):
    """Engage / release the Stage 3 kill switch (var/run/stage3.kill); audited."""
    from app.db.engine import get_sessionmaker
    from app.features import locks

    if state.lower() not in ("on", "off"):
        raise typer.BadParameter("on | off")
    on = state.lower() == "on"
    locks.set_kill_switch(on, reason)

    async def _go():
        async with get_sessionmaker()() as s:
            await locks.record_event(s, "KILL_ON" if on else "KILL_OFF", "RUN", "cli",
                                     {"reason": reason, "file": str(locks.KILL_FILE)})
            await s.commit()

    asyncio.run(_go())
    typer.echo(f"Stage 3 kill switch {'ENGAGED' if on else 'released'}")


@acceptance_app.command("stage3")
def acceptance_stage3(
    run_tests: bool = typer.Option(False, "--run-tests", help="also run the full test suite"),
    out: str = typer.Option(None, "--out", help="JSON report (default: backend/var/acceptance/"
                            "stage3.json, whatever the working directory)"),
    md: str = typer.Option(None, "--md", help="regenerate the acceptance document here "
                           "(default: docs/STAGE_3_ACCEPTANCE.md; '' = no)"),
):
    """Stage 3 gate: criteria A-O and the readiness levels. Read-only. Never
    declares Stage 3 COMPLETE unless every prerequisite and production evidence hold."""
    import json as _json
    import pathlib

    from app.acceptance import stage3 as S3
    from app.acceptance.stage1 import anchored
    from app.db.engine import get_sessionmaker

    out = out or str(anchored("var/acceptance/stage3.json"))
    md = str(anchored("../docs/STAGE_3_ACCEPTANCE.md").resolve()) if md is None else md

    tests = S3.run_tests() if run_tests else None

    async def _go():
        async with get_sessionmaker()() as s:
            return await S3.evaluate(s, tests)

    rep = asyncio.run(_go())
    pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(out).write_text(_json.dumps(rep, indent=2, default=str))
    if md:
        pathlib.Path(md).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(md).write_text(S3.to_markdown(rep))
    for c in rep["criteria"]:
        typer.echo(f"{c['id']}  {c['status']:8} {c['question']}")
    for lv in rep["levels"]:
        typer.echo(f"{'YES' if lv['reached'] else 'no':4} {lv['level']}")
    typer.echo(f"STAGE 3: {rep['overall']}")
    raise typer.Exit(0 if rep["overall"] == "COMPLETE" else 1)



news_app = typer.Typer(help="multi-source news (DRY_RUN files; SHADOW writes LOCKED)")
app.add_typer(news_app, name="news")


@news_app.command("sources")
def news_sources():
    """The source registry: status, compliance, cadence (no network, no database)."""
    from app.news.decisions import DECISIONS
    from app.news.sources import SOURCES

    for s in SOURCES.values():
        cad = (f"{s.market_interval_s}s/{s.off_interval_s}s/{s.weekend_interval_s}s"
               if s.market_interval_s else "-")
        typer.echo(f"{s.key:22} {s.status:11} compliance={s.compliance:8} tier={s.tier} "
                   f"cadence(mkt/off/wkend)={cad:16} {s.note}")
    typer.echo("")
    for k, v in DECISIONS.items():
        typer.echo(f"{k:16} {v['status']}")


@news_app.command("health")
def news_health():
    """Per-source health from the DRY_RUN state files (no network)."""
    import json as _json

    from app.core.clock import now as _now
    from app.news import http as H
    from app.news.collector import DRYRUN_DIR, KILL_FILE, DryRunRecorder
    from app.news.sources import SOURCES

    typer.echo(f"kill switch: {'ENGAGED' if KILL_FILE.exists() else 'off'}")
    for s in SOURCES.values():
        if s.status == "UNSUPPORTED":
            typer.echo(f"{s.key:22} UNSUPPORTED  {s.note}")
            continue
        if s.parse is None:
            typer.echo(f"{s.key:22} DISABLED     adapter not implemented")
            continue
        if not (DRYRUN_DIR / s.key / "state.json").exists():
            typer.echo(f"{s.key:22} DISABLED     never polled")
            continue
        r = DryRunRecorder(s)
        h = H.health(r.http, last_ok=r.last_ok, stale_after_s=3 * max(s.off_interval_s, 300))
        typer.echo(f"{s.key:22} {h:12} polls={r.polls} items={len(r.seen)} "
                   f"last_ok={r.last_ok.isoformat() if r.last_ok else None} "
                   f"recent={_json.dumps(r.http.history[-5:])} "
                   f"age_s={int((_now() - r.last_ok).total_seconds()) if r.last_ok else None}")


@news_app.command("dry-run")
def news_dry_run(
    source: str = typer.Option("NSE_ANNOUNCEMENTS", "--source",
                               help="a source key, a comma-separated list, or MEDIA "
                                    "(every implemented media adapter)"),
    polls: int = typer.Option(1, "--polls", help="number of polls (spaced by the source cadence)"),
    until: str = typer.Option(None, "--until", help="poll until HH:MM today or an ISO "
                              "date-time with offset, e.g. 2026-09-29T15:45+05:30 "
                              "(overrides --polls)"),
):
    """DRY_RUN: poll a source politely and write evidence files under
    var/news/dryrun/<source>/. No database write; entity links read the
    instrument universe read-only."""
    import datetime as _dt

    from app.core.clock import IST
    from app.core.clock import now as _now
    from app.features.locks import LockRefused
    from app.news import collector as C
    from app.news import locks as NL

    from app.news.sources import SOURCES

    keys = ([k for k, s in SOURCES.items() if s.enrich in ("HEADLINE", "REGULATOR") and s.parse
             and s.status != "UNSUPPORTED"] if source.upper() == "MEDIA"
            else [k.strip() for k in source.split(",") if k.strip()])
    for k in keys:
        rep = NL.check(k, mode="DRY_RUN", token=None)
        if not rep.ok:
            for c in rep.conditions:
                typer.echo(f"{k}: {'PASS' if c['ok'] else 'FAIL':5} {c['name']:20} {c['detail']}")
            raise typer.Exit(3)
    end = None
    if until and "T" in until:
        end = _dt.datetime.fromisoformat(until)
        if end.tzinfo is None:
            raise typer.BadParameter("--until needs a UTC offset, e.g. +05:30")
    elif until:
        hh, mm = (int(x) for x in until.split(":"))
        end = _dt.datetime.combine(_now().astimezone(IST).date(), _dt.time(hh, mm), tzinfo=IST)
    try:
        res = asyncio.run(C.dry_run_many(keys, polls=polls, until=end))
    except LockRefused as e:
        typer.echo(str(e))
        raise typer.Exit(3) from None
    for k, out in res.items():
        if isinstance(out, str):
            typer.echo(f"{k:22} FAILED {out}")
            continue
        for p in out:
            typer.echo(f"{k:22} {p['finished_at']} {p['outcome']:13} http={p['http_status']} "
                       f"seen={p['items_seen']} new={p['items_new']} "
                       f"changed={p['items_changed']} backlog={p['backlog']}"
                       + (f" error={p['error']}" if p['error'] else ""))


@news_app.command("report")
def news_report(
    source: str = typer.Option("NSE_ANNOUNCEMENTS", "--source"),
    day: str = typer.Option(None, "--day", help="IST date (default today)"),
):
    """Summarise a DRY_RUN day: polls, items, latency, duplicates, mapping."""
    import json as _json

    from app.news.collector import DRYRUN_DIR
    from app.news.report import summarise
    from app.news.sources import SOURCES

    src = SOURCES[source]
    typer.echo(_json.dumps(summarise(DRYRUN_DIR / source, day,
                                     expected_interval_s=max(src.off_interval_s, 300)),
                           indent=2, default=str))


@news_app.command("review-sample")
def news_review_sample(source: str = typer.Option(..., "--source"),
                       n: int = typer.Option(50, "--n")):
    """Write a sample of MAPPED items to var/news/review/<SOURCE>.json for a human to
    judge (the mapping criterion of `prajna acceptance news`). Never overwrites."""
    from app.acceptance.news import review_sample

    typer.echo(str(review_sample(source, n)))


@news_app.command("poll")
def news_poll(
    source: str = typer.Option("NSE_ANNOUNCEMENTS", "--source"),
    commit: bool = typer.Option(False, "--commit", help="required: SHADOW database write (LOCKED)"),
    token: str = typer.Option(None, "--token", envvar="PRAJNA_SUPPLIED_TOKEN"),
):
    """SHADOW: one poll written to the news_* tables (invisible to Stage 2/3/API).
    LOCKED: needs the source's own flag PRAJNA_NEWS_<SRC>_ENABLED, kill switch off,
    source compliance APPROVED, the source PASSING `prajna acceptance news`,
    Stage 2 PASS and a write token; refusals exit 3 and are audited."""
    import json as _json

    from app.db.engine import get_sessionmaker
    from app.features.locks import LockRefused
    from app.news.store import poll_shadow

    if not commit:
        typer.echo("news poll writes: pass --commit (lock-checked). Read-only: prajna news dry-run")
        raise typer.Exit(2)

    async def _go():
        async with get_sessionmaker()() as s:
            return await poll_shadow(s, source, token=token)

    try:
        typer.echo(_json.dumps(asyncio.run(_go()), indent=2, default=str))
    except LockRefused as e:
        for c in e.report.conditions:
            typer.echo(f"{'PASS' if c['ok'] else 'FAIL':5} {c['name']:20} {c['detail']}")
        typer.echo("REFUSED: news SHADOW polling is locked (audited in news_audit); nothing written")
        raise typer.Exit(3) from None


@news_app.command("kill")
def news_kill(state: str = typer.Argument(..., help="on | off"),
              reason: str = typer.Option("", "--reason")):
    """Engage / release the news kill switch (stops DRY_RUN and SHADOW polling); audited."""
    from app.db.engine import get_sessionmaker
    from app.news import locks as NL

    if state.lower() not in ("on", "off"):
        raise typer.BadParameter("on | off")
    on = state.lower() == "on"
    NL.set_kill(on, reason)

    async def _go():
        async with get_sessionmaker()() as s:
            await NL.audit(s, "KILL_ON" if on else "KILL_OFF", None, "cli", {"reason": reason})
            await s.commit()

    asyncio.run(_go())
    typer.echo(f"news kill switch {'ENGAGED' if on else 'released'}")



@acceptance_app.command("news")
def acceptance_news(
    run_tests: bool = typer.Option(False, "--run-tests", help="also run the news tests"),
    out: str = typer.Option(None, "--out", help="JSON report (default: backend/var/acceptance/"
                            "news.json, whatever the working directory)"),
    md: str = typer.Option(None, "--md", help="regenerate the acceptance document here "
                           "(default: docs/NEWS_MULTI_SOURCE_ACCEPTANCE.md; '' = no)"),
):
    """Per-source news acceptance (read-only). A PASS unlocks nothing by itself."""
    import json as _json
    import pathlib

    from app.acceptance import news as NA
    from app.acceptance.stage1 import anchored

    out = out or str(anchored("var/acceptance/news.json"))
    md = str(anchored("../docs/NEWS_MULTI_SOURCE_ACCEPTANCE.md").resolve()) if md is None else md

    rep = NA.evaluate(NA.run_tests() if run_tests else None)
    pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(out).write_text(_json.dumps(rep, indent=2, default=str))
    if md:
        pathlib.Path(md).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(md).write_text(NA.to_markdown(rep))
    for k, v in rep["sources"].items():
        typer.echo(f"{k:28} {v['status']:8} " + " ".join(
            f"{c}={x['status']}" for c, x in v["criteria"].items()))
    typer.echo(f"NEWS: {rep['overall']}")
    raise typer.Exit(0 if rep["overall"] == "PASS" else 1)

if __name__ == "__main__":
    app()
