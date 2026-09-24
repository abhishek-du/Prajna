"""Upstox global instruments (global.json.gz) -> instrument rows.

    download (public asset, no token) -> PayloadStore.put (raw first)
      -> parse: every row must carry exactly the measured field set
      -> instrument: one CURRENT row per key (valid_from = IST fetch date)

Measured 2026-09-24: 13 rows, segments GLOBAL_INDEX (S&P ^GSPC, Dow ^DJI,
FTSE, DAX, CAC 40, Nikkei, Hang Seng, US Tech 100, GIFT NIFTY, US 30 futures)
and GLOBAL_INDICATOR (USD INR, Brent, WTI). The file has no ISIN, lot size or
tick size (all empty/0); those columns stay NULL rather than store "0" as if it
were a real lot size. Country, latency and trading hours are kept in the
archived raw payload.

Same rules as M3.0 (never overwrite): identical current row = no-op; a
different current row = DUPLICATE_KEY FAIL. Stream instrument.global, so the
NSE master load (instrument.current) and this one never judge each other.
"""

from __future__ import annotations

import gzip
import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import insert, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.identity import GLOBAL_SEGMENTS
from app.contracts.knowable import for_snapshot_download
from app.contracts.provenance import AnomalyKind, AnomalySeverity, Source
from app.core.clock import IST
from app.core.errors import IngestCheckFailed
from app.db.models import Instrument
from app.ingest.runner import IngestRunner
from app.storage.payload_store import PayloadStore, StoredPayload

SOURCE = Source.UPSTOX_ASSETS.value
STREAM = "instrument.global"
GLOBAL_URL = "https://assets.upstox.com/market-quote/instruments/exchange/global.json.gz"
FIELDS = frozenset({
    "asset_key", "asset_symbol", "asset_type", "country", "end_time", "exchange",
    "exchange_token", "freeze_quantity", "instrument_key", "instrument_type", "isin", "latency",
    "lot_size", "minimum_lot", "mtf_bracket", "mtf_enabled", "name", "price_quote_unit",
    "qty_multiplier", "segment", "start_time", "strike_price", "tick_size", "trading_symbol",
    "underlying_key", "underlying_symbol", "underlying_type", "week_days", "weekly"})
ATTRS = ("segment", "exchange", "trading_symbol", "name")
_INFINITY = literal_column("'infinity'::date")


class GlobalMasterError(Exception):
    pass


def parse_global(data: bytes) -> list[dict[str, Any]]:
    """gzip JSON list -> instrument column dicts. Raises on any contract breach."""
    try:
        rows = json.loads(gzip.decompress(data))
    except (OSError, ValueError) as e:
        raise GlobalMasterError(f"not a gzip JSON file: {e}") from None
    if not isinstance(rows, list) or not rows:
        raise GlobalMasterError("empty or not a list")
    out, seen = [], set()
    for r in rows:
        if not isinstance(r, dict) or set(r) != FIELDS:
            diff = sorted(set(r) ^ FIELDS) if isinstance(r, dict) else r
            raise GlobalMasterError(f"fields differ: {diff}")
        seg, key, sym = r["segment"], r["instrument_key"], r["trading_symbol"]
        if seg not in GLOBAL_SEGMENTS:
            raise GlobalMasterError(f"segment {seg!r} is not a global segment")
        # The key is <segment>|<code>; the code is usually the trading symbol but
        # not always (GIFT NIFTY: key "GLOBAL_INDEX|SGX NIFTY", measured).
        if not isinstance(key, str) or not key.startswith(f"{seg}|") or not sym:
            raise GlobalMasterError(f"instrument_key {key!r} is not {seg}|<code>")
        if key in seen:
            raise GlobalMasterError(f"duplicate key {key!r}")
        seen.add(key)
        out.append({"instrument_key": key, "segment": seg, "exchange": r["exchange"],
                    "trading_symbol": sym, "name": r["name"] or None})
    return sorted(out, key=lambda x: x["instrument_key"])


@dataclass(slots=True)
class GlobalLoadReport:
    committed: bool
    payload_sha256: str
    run_id: uuid.UUID | None = None
    rows_in_file: int = 0
    inserted: int = 0
    already_current: int = 0
    status: str = "RUNNING"
    error: str | None = None
    keys: list[str] = field(default_factory=list)


async def load_global_instruments(session: AsyncSession, stored: StoredPayload, *,
                                  commit: bool, token: str | None,
                                  operator: str = "cli") -> GlobalLoadReport:
    rep = GlobalLoadReport(committed=commit, payload_sha256=stored.sha256)
    valid_from = stored.fetched_at.astimezone(IST).date()
    runner = IngestRunner(session, source=SOURCE, stream=STREAM, vendor_endpoint=GLOBAL_URL,
                          request_params={"payload_sha256": stored.sha256,
                                          "valid_from": str(valid_from)},
                          operator=operator, logical_date=valid_from)
    ctx = await runner.open(commit=commit, token=token)
    rep.run_id = ctx.run_id
    checks = ctx.checks
    try:
        if commit:
            await runner.record_payload(stored, http_status=200, vendor_endpoint=GLOBAL_URL)
        try:
            rows = parse_global(PayloadStore.read(stored.path, stored.sha256))
        except GlobalMasterError as e:
            checks.add(AnomalySeverity.FAIL, AnomalyKind.SCHEMA_DRIFT, "global.json.gz",
                       error=str(e)[:300])
            raise IngestCheckFailed(str(e)) from None
        rep.rows_in_file, rep.keys = len(rows), [r["instrument_key"] for r in rows]
        current = {i.instrument_key: i for i in (await session.execute(
            select(Instrument).where(Instrument.instrument_key.in_(rep.keys),
                                     Instrument.valid_to == _INFINITY))).scalars()}
        k = for_snapshot_download(stored.fetched_at)
        fresh = []
        for r in rows:
            old = current.get(r["instrument_key"])
            if old is None:
                fresh.append({**r, "valid_from": valid_from, "source": SOURCE,
                              "run_id": ctx.run_id, "payload_sha256": stored.sha256,
                              "fetched_at": stored.fetched_at, "knowable_at": k.at,
                              "knowable_at_verified": k.verified,
                              "knowable_at_basis": k.basis[:200]})
            elif any(getattr(old, a) != r[a] for a in ATTRS):
                checks.add(AnomalySeverity.FAIL, AnomalyKind.DUPLICATE_KEY, r["instrument_key"],
                           reason="current global instrument differs; never overwritten",
                           current={a: getattr(old, a) for a in ATTRS},
                           new={a: r[a] for a in ATTRS})
            else:
                rep.already_current += 1
        checks.raise_if_failed()
        if commit and fresh:
            await session.execute(insert(Instrument), fresh)
            rep.inserted = len(fresh)
        await runner.finalize(rows_written=rep.inserted,
                              outcome={"rows_in_file": rep.rows_in_file, "keys": rep.keys,
                                       "inserted": rep.inserted,
                                       "already_current": rep.already_current})
        rep.status = "COMPLETE"
        return rep
    except IngestCheckFailed as e:
        await runner.fail(str(e))
        rep.status, rep.error, rep.inserted = "FAILED", str(e)[:500], 0
        return rep
    except BaseException as e:
        await runner.fail(f"{type(e).__name__}: {e}")
        raise
