"""Synthetic Upstox V3 frames, built with the pinned generated classes.

These are NOT recordings of live traffic (none exists yet: blocker B0). They
are wire-valid FeedResponse messages with plausible values, so the parser and
replay can be tested offline. Golden live frames replace them once captured.
"""

from __future__ import annotations

import datetime as _dt

from app.core.clock import IST, UTC
from app.vendor.upstox.proto import MarketDataFeed_pb2 as pb

SESSION = _dt.date(2026, 9, 24)
RELIANCE = "NSE_EQ|INE002A01018"
NIFTYBEES = "NSE_EQ|INF204KB14I2"   # an ETF: INF ISIN, tradeable EQ series


def ist(h: int, m: int, s: int = 0, ms: int = 0, day: _dt.date = SESSION) -> _dt.datetime:
    local = _dt.datetime(day.year, day.month, day.day, h, m, s, ms * 1000, tzinfo=IST)
    return local.astimezone(UTC)


def epoch_ms(at: _dt.datetime) -> int:
    return round(at.timestamp() * 1000)


def varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b, n = n & 0x7F, n >> 7
        out.append(b | 0x80 if n else b)
        if not n:
            return bytes(out)


def market_ff(
    *, iep=2458.1, ieq=12000, iiq_total=3400, iiq_m=150, rp=2440.0, tbq=150000.0,
    tsq=120000.0, cas=True, ltp=2440.0, cp=2440.0, ltt=None, ltpc_iep=2458.1,
    rungs=5, mode=pb.full_d5, atp=0.0, vtt=0,
) -> pb.Feed:
    f = pb.Feed(requestMode=mode)
    ff = f.fullFeed.marketFF
    ff.iep, ff.ieq, ff.iiqTotal, ff.iiqM, ff.rp = iep, ieq, iiq_total, iiq_m, rp
    ff.tbq, ff.tsq, ff.casEligible, ff.atp, ff.vtt = tbq, tsq, cas, atp, vtt
    ff.ltpc.ltp, ff.ltpc.cp, ff.ltpc.ltq = ltp, cp, 0
    if ltt is not None:
        ff.ltpc.ltt = epoch_ms(ltt)
    if ltpc_iep is not None:
        ff.ltpc.iep.value = ltpc_iep
    for i in range(rungs):
        ff.marketLevel.bidAskQuote.add(
            bidQ=100 * (i + 1), bidP=round(iep - 0.05 * (i + 1), 2),
            askQ=90 * (i + 1), askP=round(iep + 0.05 * (i + 1), 2),
        )
    return f


def frame(feeds: dict[str, pb.Feed], at: _dt.datetime, *, kind=pb.live_feed,
          market_info: pb.MarketInfo | None = None) -> bytes:
    fr = pb.FeedResponse(type=kind, currentTs=epoch_ms(at))
    for k, v in feeds.items():
        fr.feeds[k].CopyFrom(v)
    if market_info is not None:
        fr.marketInfo.CopyFrom(market_info)
    return fr.SerializeToString()


def status_frame(at: _dt.datetime, statuses: dict[str, tuple[str, _dt.datetime]],
                 segment_status: dict[str, int] | None = None) -> bytes:
    mi = pb.MarketInfo()
    for seg, (st, when) in statuses.items():
        mi.preOpenSessionStatus[seg].status = st
        mi.preOpenSessionStatus[seg].updatedTime = epoch_ms(when)
    for seg, v in (segment_status or {}).items():
        mi.segmentStatus[seg] = v
    return frame({}, at, kind=pb.market_info, market_info=mi)
