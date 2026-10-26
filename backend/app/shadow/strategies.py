"""The two CANDIDATE specs (pre-registration §6), PURE. Each returns at most one candidate
per name per session: the plan (entry from the next 1m open, stop, target, time stop,
size factor), the 6-point checklist and the evidence, or a skip with its reason.

The first bar that meets a strategy's signal conditions defines the name's candidate; a
rejected candidate is logged as a skip and the name is done for the session (no search
for a variant that passes)."""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Any

from app.shadow import indicators as I
from app.shadow.bars import IBar, NameDay, at, last_until
from app.shadow.spec import BOOK, S1, S2, STRAT


@dataclass
class Candidate:
    strategy: str
    key: str
    side: int                                  # +1 long, -1 short
    signal_at: _dt.datetime                    # the 15m signal bar's end (UTC)
    entry_at: _dt.datetime                     # the 1m bar the entry fills on (its start)
    entry_raw: float                           # that bar's open (before spread/slippage)
    stop: float
    target: float
    atr: float
    time_stop: _dt.datetime                    # exit at the close of the 1m bar ending here
    time_reason: str                           # EOD | TIME_NOT_WORKING
    size_factor: float
    checklist: dict[str, bool]
    rank: tuple
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def rrr(self) -> float:
        risk = abs(self.entry_raw - self.stop)
        return (self.side * (self.target - self.entry_raw)) / risk if risk > 0 else 0.0

    @property
    def score(self) -> int:
        return sum(self.checklist.values())


@dataclass
class Skip:
    strategy: str
    key: str
    reason: str
    signal_at: _dt.datetime | None
    detail: dict[str, Any] = field(default_factory=dict)


Result = Candidate | Skip | None


def _slot_avg(nd: NameDay, session: _dt.date, slot: _dt.time, n: int) -> float | None:
    vols = [b.volume for b, d in zip(nd.m15, nd.m15_dates) if d < session
            and b.ist_start() == slot]
    vols = vols[-n:]
    return sum(vols) / len(vols) if len(vols) >= max(1, (7 * n) // 10) else None


def _entry_bar(nd: NameDay, t: _dt.datetime) -> IBar | None:
    for b in nd.m1:
        if b.start == t:
            return b
        if b.start > t:
            return None
    return None


def _hm(s: str) -> _dt.time:
    h, m = (int(x) for x in s.split(":"))
    return _dt.time(h, m)


def _series(nd: NameDay):
    h = [b.high for b in nd.m15]
    lo = [b.low for b in nd.m15]
    c = [b.close for b in nd.m15]
    return h, lo, c


def _verdict(c: Candidate, mandatory: tuple[str, ...]) -> Result:
    if not all(c.checklist[p] for p in mandatory if p != "p6_rrr") or c.score < BOOK["checklist_min"]:
        return Skip(c.strategy, c.key, "CHECKLIST_LT4", c.signal_at,
                    {"checklist": c.checklist, **c.evidence})
    if c.rrr < BOOK["rrr_min"]:
        return Skip(c.strategy, c.key, "SKIP_RRR", c.signal_at,
                    {"rrr": round(c.rrr, 4), "checklist": c.checklist, **c.evidence})
    return c


def orb_breadth(nd: NameDay, session: _dt.date, nifty_1m: list[IBar],
                breadth: dict[_dt.datetime, float | None]) -> Result:
    """S1. breadth: share of the universe above its open, keyed by the 15m bar end."""
    p = STRAT[S1]
    today = [i for i, d in enumerate(nd.m15_dates) if d == session]
    if not today or not nifty_1m:
        return None
    first = nd.m15[today[0]]
    if first.ist_start() != _dt.time(9, 15) or first.ist_end() != _hm(p["or_end"]):
        return None
    hi, lo = first.high, first.low
    width = hi - lo
    h, l_, c = _series(nd)
    atr = I.atr(h, l_, c, p["atr_n"])
    adx = I.adx(h, l_, c, 14)
    rsi = I.rsi(c, 14)
    n_open = nifty_1m[0].open
    for i in today[1:]:
        b = nd.m15[i]
        if not (_hm(p["signal_from"]) <= b.ist_end() <= _hm(p["signal_to"])):
            continue
        side = 1 if b.close > hi else -1 if b.close < lo else 0
        if side == 0:
            continue
        avg = _slot_avg(nd, session, b.ist_start(), p["vol_sessions"])
        vr = b.volume / avg if avg else None
        if vr is None or vr < p["vol_ratio_min"]:
            continue
        nb = last_until(nifty_1m, b.end)
        br = breadth.get(b.end)
        if nd.ema50_1d is None or nd.prev_close is None or nb is None or br is None:
            continue
        dow = (nd.prev_close > nd.ema50_1d and nb.close > n_open and br > p["breadth_long"]) \
            if side > 0 else \
            (nd.prev_close < nd.ema50_1d and nb.close < n_open and br < p["breadth_short"])
        if not dow:
            continue
        eb = _entry_bar(nd, b.end)
        if eb is None or atr[i] is None:
            return Skip(S1, nd.key, "NO_INTRADAY_BARS", b.end,
                        {"entry_bar": eb is not None, "atr": atr[i]})
        e = eb.open
        level = hi if side > 0 else lo
        stop = min(level, e - p["stop_atr_min"] * atr[i]) if side > 0 else \
            max(level, e + p["stop_atr_min"] * atr[i])
        target = hi + width if side > 0 else lo - width
        rl, rh = p["ind_rsi_long"] if side > 0 else p["ind_rsi_short"]
        ind = adx[i] is not None and adx[i] >= p["ind_adx_min"] and rsi[i] is not None \
            and rl <= rsi[i] <= rh
        cand = Candidate(
            S1, nd.key, side, b.end, eb.start, e, stop, target, atr[i],
            at(session, p["exit_eod"]), "EOD", 1.0 if ind else 0.5,
            {"p1_pattern": True,
             "p2_structure_stop": abs(e - level) / e <= p["structure_max_pct"],
             "p3_volume": True, "p4_dow": True, "p5_indicators": ind, "p6_rrr": False},
            (0, 0.0),
            {"or_high": hi, "or_low": lo, "vol_ratio": vr, "breadth_above_open": br,
             "adx15": adx[i], "rsi15": rsi[i], "signal_close": b.close})
        cand.checklist["p6_rrr"] = cand.rrr >= BOOK["rrr_min"]
        cand.rank = (cand.score, vr)
        return _verdict(cand, ("p1_pattern", "p3_volume", "p6_rrr"))
    return None


def vwap_revert(nd: NameDay, session: _dt.date) -> Result:
    """S2."""
    p = STRAT[S2]
    today = [i for i, d in enumerate(nd.m15_dates) if d == session]
    if not today or nd.prev_close is None or nd.adx14_1d is None:
        return None
    h, l_, c = _series(nd)
    lo_b, mid, hi_b = I.bollinger(c, p["bb_n"], p["bb_k"])
    rsi = I.rsi(c, p["rsi_n"])
    atr = I.atr(h, l_, c, p["atr_n"])
    for i in today:
        b = nd.m15[i]
        if not (_hm(p["signal_from"]) <= b.ist_end() <= _hm(p["signal_to"])):
            continue
        if lo_b[i] is None or rsi[i] is None:
            continue
        m1 = [x for x in nd.m1 if x.end <= b.end]
        vw = I.vwap([x.high for x in m1], [x.low for x in m1], [x.close for x in m1],
                    [x.volume for x in m1])[-1] if m1 else None
        if vw is None:
            continue
        if b.close <= lo_b[i] and rsi[i] < p["rsi_low"] and b.close < vw:
            side = 1
        elif b.close >= hi_b[i] and rsi[i] > p["rsi_high"] and b.close > vw:
            side = -1
        else:
            continue
        if nd.adx14_1d >= p["stock_adx_max"]:
            continue                                   # the stock is not ranging: no signal
        move = b.close / nd.prev_close - 1
        if abs(move) >= p["max_move_prev_close"]:
            return Skip(S2, nd.key, "MOVE_GT_3PCT", b.end, {"move": move})
        eb = _entry_bar(nd, b.end)
        if eb is None or atr[i] is None:
            return Skip(S2, nd.key, "NO_INTRADAY_BARS", b.end,
                        {"entry_bar": eb is not None, "atr": atr[i]})
        e = eb.open
        stop = e - side * p["stop_atr"] * atr[i]
        avg = _slot_avg(nd, session, b.ist_start(), p["vol_sessions"])
        vr = b.volume / avg if avg else None
        full = rsi[i] < p["rsi_full_low"] if side > 0 else rsi[i] > p["rsi_full_high"]
        ts = min(b.end + _dt.timedelta(minutes=15 * p["time_stop_bars15"]),
                 at(session, p["exit_eod"]))
        cand = Candidate(
            S2, nd.key, side, b.end, eb.start, e, stop, mid[i], atr[i], ts,
            "TIME_NOT_WORKING" if ts < at(session, p["exit_eod"]) else "EOD",
            1.0 if full else 0.5,
            {"p1_pattern": True, "p2_structure_stop": p["stop_atr"] * atr[i] / e <= 0.04,
             "p3_volume": vr is not None and vr >= p["vol_ratio_min"], "p4_dow": True,
             "p5_indicators": full, "p6_rrr": False},
            (0, 0.0),
            {"bb_low": lo_b[i], "bb_mid": mid[i], "bb_high": hi_b[i], "rsi15": rsi[i],
             "vwap": vw, "vol_ratio": vr, "move_prev_close": move,
             "adx14_1d": nd.adx14_1d, "signal_close": b.close})
        cand.checklist["p6_rrr"] = cand.rrr >= BOOK["rrr_min"]
        cand.rank = (abs(b.close - vw) / atr[i],)
        return _verdict(cand, ("p1_pattern", "p3_volume", "p6_rrr"))
    return None
