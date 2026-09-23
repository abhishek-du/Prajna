"""Upstox Market Data Feed V3 frame -> typed pre-open rows. PURE.

No network, no database, no filesystem: bytes in, rows and issues out. That is
what makes replay deterministic — the same archived frame always produces the
same rows, whether it arrives live or from disk months later.

What becomes a row:
  * Feed.fullFeed.marketFF  -> one preopen_tick (+ preopen_book rungs)
  * Feed.fullFeed.indexFF   -> one preopen_tick with its LTPC fields only
  * Feed.ltpc               -> one preopen_tick with its LTPC fields only
  * MarketInfo.preOpenSessionStatus[segment] -> one preopen_session_status

What does NOT become a row, deliberately, and is kept in the archive instead:
  * marketOHLC and optionGreeks (no pre-open meaning; not in the M1 schema)
  * MarketInfo.segmentStatus / casMarketStatus (returned on ParsedFrame for
    the caller to report; no M1 table)
  * Feed.firstLevelWithGreeks (options mode; never subscribed by M1) — an
    issue is raised if it ever appears.

Vendor semantics that proto3 cannot express, carried forward honestly:
  * Scalars have no presence: iep = 0.0 on the wire is indistinguishable from
    "not sent" (open blocker B8). The value is stored as sent.
  * LTPC.iep IS a DoubleValue wrapper, so its absence is real and becomes NULL.
  * Feed.requestMode is read per feed from the wire, so which mode Upstox
    actually served (B6) is recorded per row rather than assumed.
  * LTPC.ltt == 0 means "no trade time", not 1970; it becomes NULL.
"""

from __future__ import annotations

import datetime as _dt
import math
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from google.protobuf.message import DecodeError, Message
from google.protobuf.unknown_fields import UnknownFieldSet

from app.contracts.knowable import Knowable, for_preopen_status, for_preopen_tick
from app.contracts.provenance import AnomalyKind, AnomalySeverity, Source, payload_sha256
from app.core.clock import epoch_ms_to_utc, ist_date_of, to_utc
from app.vendor.upstox.proto import MarketDataFeed_pb2 as pb

SOURCE = Source.UPSTOX_WS_V3.value
MAX_BOOK_RUNGS = 30  # full_d30; the preopen_book CHECK enforces the same bound

# Column scale, mirrored from app/db/models/preopen.py. A vendor value that
# would lose digits in the column is reported, never silently rounded.
_PRICE_SCALE = 4
_QTY_SCALE = 2
_IV_SCALE = 6


class FrameDecodeError(Exception):
    """The bytes are not a FeedResponse. The archived frame stays replayable."""


@dataclass(frozen=True, slots=True)
class Issue:
    severity: AnomalySeverity
    kind: AnomalyKind
    subject: str | None
    detail: dict[str, Any]


@dataclass(frozen=True, slots=True)
class BookRung:
    rung_no: int
    bid_qty: int
    bid_price: Decimal | None
    ask_qty: int
    ask_price: Decimal | None


@dataclass(frozen=True, slots=True)
class Provenance:
    source: str
    payload_sha256: str
    fetched_at: _dt.datetime
    knowable_at: _dt.datetime
    knowable_at_verified: bool
    knowable_at_basis: str

    def columns(self) -> dict[str, Any]:
        return {
            "source": self.source, "payload_sha256": self.payload_sha256,
            "fetched_at": self.fetched_at, "knowable_at": self.knowable_at,
            "knowable_at_verified": self.knowable_at_verified,
            "knowable_at_basis": self.knowable_at_basis,
        }


@dataclass(frozen=True, slots=True)
class TickRow:
    session_date: _dt.date
    instrument_key: str
    frame_seq: int
    vendor_ts: _dt.datetime
    feed_type: str
    request_mode: str
    provenance: Provenance
    iep: Decimal | None = None
    ieq: int | None = None
    iiq_total: int | None = None
    iiq_m: int | None = None
    rp: Decimal | None = None
    tbq: Decimal | None = None
    tsq: Decimal | None = None
    cas_eligible: bool | None = None
    atp: Decimal | None = None
    vtt: int | None = None
    oi: Decimal | None = None
    iv: Decimal | None = None
    ltp: Decimal | None = None
    ltt: _dt.datetime | None = None
    ltq: int | None = None
    cp: Decimal | None = None
    ltpc_iep: Decimal | None = None
    book: tuple[BookRung, ...] = ()

    def columns(self) -> dict[str, Any]:
        """preopen_tick columns, minus run_id (the writer owns the run)."""
        cols = {
            k: getattr(self, k) for k in (
                "session_date", "instrument_key", "frame_seq", "vendor_ts", "feed_type",
                "request_mode", "iep", "ieq", "iiq_total", "iiq_m", "rp", "tbq", "tsq",
                "cas_eligible", "atp", "vtt", "oi", "iv", "ltp", "ltt", "ltq", "cp",
                "ltpc_iep",
            )
        }
        return {**cols, **self.provenance.columns()}


@dataclass(frozen=True, slots=True)
class StatusRow:
    session_date: _dt.date
    segment: str
    status: str
    vendor_updated_at: _dt.datetime
    observed_at: _dt.datetime
    provenance: Provenance

    def columns(self) -> dict[str, Any]:
        return {
            "session_date": self.session_date, "segment": self.segment,
            "status": self.status, "vendor_updated_at": self.vendor_updated_at,
            "observed_at": self.observed_at, **self.provenance.columns(),
        }


@dataclass(slots=True)
class ParsedFrame:
    frame_seq: int
    payload_sha256: str
    feed_type: str
    vendor_ts: _dt.datetime | None
    ticks: list[TickRow] = field(default_factory=list)
    statuses: list[StatusRow] = field(default_factory=list)
    segment_status: dict[str, str] = field(default_factory=dict)
    cas_status: dict[str, dict[str, Any]] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)

    def issue(self, severity: AnomalySeverity, kind: AnomalyKind, subject: str | None,
              **detail: Any) -> None:
        self.issues.append(Issue(severity, kind, subject,
                                 {"frame_seq": self.frame_seq,
                                  "payload_sha256": self.payload_sha256, **detail}))


# ── schema drift ────────────────────────────────────────────────────────────
def find_drift(msg: Message, path: str = "") -> list[str]:
    """Every unknown field and every out-of-contract enum value, by path.

    proto3 keeps both silently: unknown fields ride along in the message and
    unknown enum values arrive as bare integers. Either may be the field a
    strategy needs, so both are surfaced.
    """
    found: list[str] = []
    here = path or msg.DESCRIPTOR.name
    for uf in UnknownFieldSet(msg):
        found.append(f"{here}#{uf.field_number}")
    for fd in msg.DESCRIPTOR.fields:
        name = f"{here}.{fd.name}"
        is_map = fd.message_type is not None and fd.message_type.GetOptions().map_entry
        if is_map:
            value_fd = fd.message_type.fields_by_name["value"]
            container = getattr(msg, fd.name)
            for key in sorted(container):
                val = container[key]
                if value_fd.message_type is not None:
                    found += find_drift(val, f"{name}[{key}]")
                elif (value_fd.enum_type is not None
                      and val not in value_fd.enum_type.values_by_number):
                    found.append(f"{name}[{key}]=enum:{val}")
        elif fd.message_type is not None:
            if fd.is_repeated:
                for i, sub in enumerate(getattr(msg, fd.name)):
                    found += find_drift(sub, f"{name}[{i}]")
            elif msg.HasField(fd.name):
                found += find_drift(getattr(msg, fd.name), name)
        elif fd.enum_type is not None:
            vals = getattr(msg, fd.name) if fd.is_repeated else [getattr(msg, fd.name)]
            for v in vals:
                if v not in fd.enum_type.values_by_number:
                    found.append(f"{name}=enum:{v}")
    return found


# ── value conversion ────────────────────────────────────────────────────────
class _Values:
    """Converts vendor doubles to Decimal, reporting anything it cannot keep."""

    def __init__(self, frame: ParsedFrame, key: str):
        self.frame, self.key = frame, key

    def dec(self, value: float, fname: str, scale: int) -> Decimal | None:
        if not math.isfinite(value):
            self.frame.issue(AnomalySeverity.FAIL, AnomalyKind.PARSE_REJECT, self.key,
                             field=fname, value=repr(value), reason="non-finite")
            return None
        d = Decimal(repr(value))
        if d != d.quantize(Decimal(1).scaleb(-scale)):
            self.frame.issue(AnomalySeverity.WARN, AnomalyKind.PARSE_REJECT, self.key,
                             field=fname, value=repr(value), column_scale=scale,
                             reason="precision exceeds column scale")
        return d

    def price(self, v: float, f: str) -> Decimal | None:
        return self.dec(v, f, _PRICE_SCALE)

    def qty(self, v: float, f: str) -> Decimal | None:
        return self.dec(v, f, _QTY_SCALE)


def _enum_name(enum_type, value: int) -> str:
    ev = enum_type.values_by_number.get(value)
    return ev.name if ev is not None else f"UNKNOWN_{value}"


def _bounded(k: Knowable, fetched_at: _dt.datetime, frame: ParsedFrame, subject: str) -> Knowable:
    """knowable_at may never postdate our receipt (and the DB CHECK agrees).

    If the vendor clock is ahead of ours, the vendor time would claim we knew
    the fact before we held it. The honest bound is fetched_at, unverified.
    """
    if k.at <= fetched_at:
        return k
    skew_ms = round((k.at - fetched_at).total_seconds() * 1000, 3)
    frame.issue(AnomalySeverity.WARN, AnomalyKind.CLOCK_SKEW, subject,
                vendor_ts=k.at.isoformat(), fetched_at=fetched_at.isoformat(), skew_ms=skew_ms)
    return Knowable(fetched_at, False,
                    f"vendor time ahead of fetched_at by {skew_ms}ms; bounded by fetched_at")


# ── the parser ──────────────────────────────────────────────────────────────
def decode(data: bytes) -> pb.FeedResponse:
    try:
        return pb.FeedResponse.FromString(data)
    except DecodeError as e:
        raise FrameDecodeError(str(e)) from None


def parse_frame(
    data: bytes, *, frame_seq: int, fetched_at: _dt.datetime, session_date: _dt.date,
) -> ParsedFrame:
    """One archived frame -> rows. Raises FrameDecodeError on undecodable bytes;
    everything else is reported as an Issue on the returned frame."""
    fetched_at = to_utc(fetched_at)
    msg = decode(data)
    sha = payload_sha256(data)

    feed_type = _enum_name(pb.Type.DESCRIPTOR, msg.type)
    vendor_ts = epoch_ms_to_utc(msg.currentTs) if msg.currentTs else None
    frame = ParsedFrame(frame_seq=frame_seq, payload_sha256=sha, feed_type=feed_type,
                        vendor_ts=vendor_ts)

    drift = find_drift(msg)
    if drift:
        frame.issue(AnomalySeverity.FAIL, AnomalyKind.SCHEMA_DRIFT, "FeedResponse",
                    unknown=drift)

    if msg.HasField("marketInfo"):
        _parse_market_info(msg.marketInfo, frame, fetched_at, session_date, sha)

    if not msg.feeds:
        return frame
    if vendor_ts is None:
        frame.issue(AnomalySeverity.FAIL, AnomalyKind.PARSE_REJECT, "FeedResponse",
                    reason="feeds present but currentTs missing", feeds=len(msg.feeds))
        return frame
    if ist_date_of(vendor_ts) != session_date:
        frame.issue(AnomalySeverity.FAIL, AnomalyKind.SESSION_MISMATCH, "FeedResponse",
                    vendor_ts=vendor_ts.isoformat(), vendor_ist_date=str(ist_date_of(vendor_ts)),
                    session_date=str(session_date))
        return frame

    k = _bounded(for_preopen_tick(vendor_ts), fetched_at, frame, "FeedResponse.currentTs")
    prov = Provenance(SOURCE, sha, fetched_at, k.at, k.verified, k.basis)

    for key in sorted(msg.feeds):
        row = _parse_feed(key, msg.feeds[key], frame, prov, session_date, vendor_ts)
        if row is not None:
            frame.ticks.append(row)
    return frame


def _parse_market_info(mi, frame: ParsedFrame, fetched_at: _dt.datetime,
                       session_date: _dt.date, sha: str) -> None:
    for seg in sorted(mi.segmentStatus):
        frame.segment_status[seg] = _enum_name(pb.MarketStatus.DESCRIPTOR, mi.segmentStatus[seg])
    for seg in sorted(mi.casMarketStatus):
        si = mi.casMarketStatus[seg]
        frame.cas_status[seg] = {"status": si.status, "updatedTime": si.updatedTime}

    for seg in sorted(mi.preOpenSessionStatus):
        si = mi.preOpenSessionStatus[seg]
        subject = f"preOpenSessionStatus[{seg}]"
        if not si.updatedTime or not si.status:
            frame.issue(AnomalySeverity.FAIL, AnomalyKind.PARSE_REJECT, subject,
                        reason="status or updatedTime missing", status=si.status,
                        updatedTime=si.updatedTime)
            continue
        updated = epoch_ms_to_utc(si.updatedTime)
        k = _bounded(for_preopen_status(updated), fetched_at, frame, subject)
        frame.statuses.append(StatusRow(
            session_date=session_date, segment=seg, status=si.status,
            vendor_updated_at=updated, observed_at=fetched_at,
            provenance=Provenance(SOURCE, sha, fetched_at, k.at, k.verified, k.basis),
        ))


def _ltpc_columns(ltpc, v: _Values) -> dict[str, Any]:
    return {
        "ltp": v.price(ltpc.ltp, "ltpc.ltp"),
        "ltt": epoch_ms_to_utc(ltpc.ltt) if ltpc.ltt else None,
        "ltq": ltpc.ltq,
        "cp": v.price(ltpc.cp, "ltpc.cp"),
        "ltpc_iep": v.price(ltpc.iep.value, "ltpc.iep") if ltpc.HasField("iep") else None,
    }


def _parse_feed(key: str, feed, frame: ParsedFrame, prov: Provenance,
                session_date: _dt.date, vendor_ts: _dt.datetime) -> TickRow | None:
    v = _Values(frame, key)
    base = {
        "session_date": session_date, "instrument_key": key, "frame_seq": frame.frame_seq,
        "vendor_ts": vendor_ts, "feed_type": frame.feed_type,
        "request_mode": _enum_name(pb.RequestMode.DESCRIPTOR, feed.requestMode),
        "provenance": prov,
    }
    which = feed.WhichOneof("FeedUnion")

    if which == "ltpc":
        return TickRow(**base, **_ltpc_columns(feed.ltpc, v))

    if which == "fullFeed":
        inner = feed.fullFeed.WhichOneof("FullFeedUnion")
        if inner == "indexFF":
            iff = feed.fullFeed.indexFF
            cols = _ltpc_columns(iff.ltpc, v) if iff.HasField("ltpc") else {}
            return TickRow(**base, **cols)
        if inner == "marketFF":
            return _market_ff(feed.fullFeed.marketFF, base, v, frame, key)
        frame.issue(AnomalySeverity.WARN, AnomalyKind.PARSE_REJECT, key,
                    reason="fullFeed with no marketFF/indexFF")
        return None

    frame.issue(AnomalySeverity.WARN, AnomalyKind.PARSE_REJECT, key,
                reason=f"feed kind {which!r} is not modelled by preopen_tick",
                request_mode=base["request_mode"])
    return None


def _market_ff(ff, base: dict[str, Any], v: _Values, frame: ParsedFrame, key: str) -> TickRow:
    quotes = list(ff.marketLevel.bidAskQuote) if ff.HasField("marketLevel") else []
    if len(quotes) > MAX_BOOK_RUNGS:
        frame.issue(AnomalySeverity.FAIL, AnomalyKind.PARSE_REJECT, key,
                    reason="book deeper than the schema admits", rungs=len(quotes),
                    max_rungs=MAX_BOOK_RUNGS)
        quotes = quotes[:MAX_BOOK_RUNGS]
    book = tuple(
        BookRung(i, q.bidQ, v.price(q.bidP, f"book[{i}].bidP"),
                 q.askQ, v.price(q.askP, f"book[{i}].askP"))
        for i, q in enumerate(quotes)
    )
    ltpc = _ltpc_columns(ff.ltpc, v) if ff.HasField("ltpc") else {}
    return TickRow(
        **base, **ltpc,
        iep=v.price(ff.iep, "iep"), ieq=ff.ieq, iiq_total=ff.iiqTotal, iiq_m=ff.iiqM,
        rp=v.price(ff.rp, "rp"), tbq=v.qty(ff.tbq, "tbq"), tsq=v.qty(ff.tsq, "tsq"),
        cas_eligible=ff.casEligible, atp=v.price(ff.atp, "atp"), vtt=ff.vtt,
        oi=v.qty(ff.oi, "oi"), iv=v.dec(ff.iv, "iv", _IV_SCALE), book=book,
    )
