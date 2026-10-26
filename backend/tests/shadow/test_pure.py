"""app/shadow pure parts: indicators, the regime rule table, the 1m path, the guards,
the strategies' rules on synthetic bars, the placebo and point-in-time reads."""

from __future__ import annotations

import datetime as _dt

import pytest

from app.shadow import book as BK
from app.shadow import fill as F
from app.shadow import indicators as I
from app.shadow import regime as RG
from app.shadow import spec as SP
from app.shadow import strategies as ST
from app.shadow.bars import IBar, NameDay, at

DAY = _dt.date(2026, 10, 7)
PREV = [_dt.date(2026, 9, 23) + _dt.timedelta(days=i) for i in range(10)]


# ── indicators ────────────────────────────────────────────────────────────────────
def test_sma_ema_stdev_bollinger():
    x = [1.0, 2, 3, 4, 5]
    assert I.sma(x, 3) == [None, None, 2.0, 3.0, 4.0]
    e = I.ema(x, 3)
    assert e[:2] == [None, None] and e[2] == 2.0 and e[3] == pytest.approx(3.0)
    lo, mid, hi = I.bollinger([2.0, 4.0], 2, 2.0)
    assert mid[1] == 3.0 and lo[1] == pytest.approx(1.0) and hi[1] == pytest.approx(5.0)


def test_rsi_atr_adx_vwap():
    up = [float(i) for i in range(1, 40)]
    assert I.rsi(up, 14)[-1] == 100.0
    assert I.rsi(up[::-1], 14)[-1] == pytest.approx(0.0)
    h = [c + 1 for c in up]
    lo = [c - 1 for c in up]
    assert I.atr(h, lo, up, 14)[-1] == pytest.approx(2.0)
    a = I.adx(h, lo, up, 14)
    assert a[26] is None and a[27] is not None and a[-1] > 90       # a pure trend
    assert I.vwap([2.0, 4.0], [2.0, 4.0], [2.0, 4.0], [1.0, 3.0])[-1] == pytest.approx(3.5)
    assert I.vwap([1.0], [1.0], [1.0], [0.0]) == [None]


# ── regime rule table ─────────────────────────────────────────────────────────────
BASE = {"nifty_adx14": 30.0, "nifty_above_ema50": True, "bank_above_ema50": True,
        "breadth_50dma": 0.65, "ad_ratio": 0.5, "vix_pct252": 0.5, "vix_chg_1d": 0.0,
        "nifty_sigma20": 0.01, "nifty_ret_1d": 0.002, "results_share": 0.0,
        "calendar_events": [], "holiday_thin": False}


@pytest.mark.parametrize("patch,state", [
    ({}, "TREND_UP"),
    ({"breadth_50dma": 0.60}, "MIXED"),                      # > 60 % strictly
    ({"bank_above_ema50": False}, "MIXED"),                  # indices must agree
    ({"nifty_above_ema50": False, "bank_above_ema50": False, "breadth_50dma": 0.3},
     "TREND_DOWN"),
    ({"nifty_adx14": 19.9}, "RANGE"),
    ({"nifty_adx14": 22.0}, "MIXED"),
    ({"nifty_adx14": None}, "MIXED"),                        # missing never satisfies a rule
    ({"calendar_events": ["RBI_MPC_DECISION"]}, "EVENT_WAIT"),
    ({"results_share": 0.05}, "EVENT_WAIT"),
    ({"vix_pct252": 0.90}, "SHOCK"),
    ({"vix_chg_1d": 0.2}, "SHOCK"),
    ({"nifty_ret_1d": -0.021}, "SHOCK"),                     # >= 2 sigma20
    ({"ad_ratio": 0.2, "calendar_events": ["X"]}, "SHOCK"),  # first match wins
])
def test_classify_order(patch, state):
    st, rule, mult = RG.classify({**BASE, **patch})
    assert st == state and mult == SP.REGIME["mult"][state] and rule[0].isdigit()


def test_holiday_thin_halves_the_multiplier():
    assert RG.classify({**BASE, "holiday_thin": True})[2] == 0.5


def test_open_gap_shock():
    b = [IBar(at(DAY, "09:15"), at(DAY, "09:16"), 102.1, 102.2, 102.0, 102.1, 0)]
    assert RG.open_features(b, 100.0, 0.01)["shock_open"] is True
    assert RG.open_features(b, 101.0, 0.01)["shock_open"] is False


# ── synthetic bars ────────────────────────────────────────────────────────────────
def _m1(day, prices, start="09:15"):
    t0 = at(day, start)
    out = []
    for i, p in enumerate(prices):
        o, h, lo, c = p if isinstance(p, tuple) else (p, p, p, p)
        out.append(IBar(t0 + _dt.timedelta(minutes=i), t0 + _dt.timedelta(minutes=i + 1),
                        o, h, lo, c, 100.0))
    return out


def _m15(day, rows):
    t0 = at(day, "09:15")
    return [IBar(t0 + _dt.timedelta(minutes=15 * i), t0 + _dt.timedelta(minutes=15 * (i + 1)),
                 *r) for i, r in enumerate(rows)]


# ── fills ─────────────────────────────────────────────────────────────────────────
def test_path_stop_first_gap_target_and_time():
    t = at(DAY, "10:00")
    eod = at(DAY, "15:15")
    m1 = _m1(DAY, [100.0] * 45 + [(100, 103, 97, 100)], start="09:15")
    # entry bar at 10:00 touches both 97 (stop) and 103 (target): the stop first
    p = F.path(m1, 1, t, 98.0, 102.0, eod, "EOD")
    assert p.reason == "STOP" and p.exit_raw == 98.0
    m1 = _m1(DAY, [100.0] * 45 + [100.0, (95, 96, 94, 95)])
    p = F.path(m1, 1, t, 98.0, 102.0, eod, "EOD")
    assert p.reason == "STOP_GAP" and p.exit_raw == 95
    m1 = _m1(DAY, [100.0] * 45 + [100.0, (101, 102.5, 100.5, 102)])
    p = F.path(m1, 1, t, 98.0, 102.0, eod, "EOD")
    assert p.reason == "TARGET" and p.exit_raw == 102.0
    p = F.path(m1, -1, t, 102.0, 98.0, eod, "EOD")              # short: 102.5 hits its stop
    assert p.reason == "STOP" and p.exit_raw == 102.0
    m1 = _m1(DAY, [100.0] * 45 + [100.0] * 70)
    ts = at(DAY, "11:00")
    p = F.path(m1, 1, t, 98.0, 102.0, ts, "TIME_NOT_WORKING")
    assert p.reason == "TIME_NOT_WORKING" and p.exit_at == ts
    assert F.path(m1, 1, at(DAY, "10:00") + _dt.timedelta(seconds=30), 98, 102, ts, "X") is None


def test_settle_costs_and_slippage():
    a = F.settle(1, 100, 100.0, 101.0, 0.0)
    b = F.settle(1, 100, 100.0, 101.0, 10.0)
    assert a["entry_px"] == pytest.approx(100.05) and a["net_inr"] > b["net_inr"]
    s = F.settle(-1, 100, 100.0, 99.0, 0.0)
    assert s["entry_px"] == pytest.approx(99.95) and s["gross_inr"] > 0


# ── guards ────────────────────────────────────────────────────────────────────────
def test_size_rule():
    assert BK.size(2.0, 1.0, 100.0, 1e9) == 5000                # 1 % of Rs 10 L / Rs 2
    assert BK.size(2.0, 0.5, 100.0, 1e9) == 2500
    assert BK.size(0.01, 1.0, 100.0, 1e9) == 10000              # notional cap Rs 10 L
    assert BK.size(2.0, 1.0, 100.0, 100_000) == 1000            # 1 % participation
    assert BK.size(2.0, 1.0, 100.0, None) == 0


def test_dd_flags():
    assert BK.dd_flags([10_000, -60_000]) == ["DD_HALF"]
    assert BK.dd_flags([-100_000]) == ["DD_HALF", "DD_HALT"]
    assert BK.dd_flags([5_000]) == []


def _cand(key, t, entry=100.0, stop=98.0, target=104.0, side=1, rank=(1.0,)):
    return ST.Candidate("s", key, side, t, t, entry, stop, target, 2.0,
                        at(DAY, "15:15"), "EOD", 1.0, {"p1_pattern": True}, rank)


def _nd(key, prices, sector=None):
    return NameDay(key, _m1(DAY, prices), [], [], 100.0, None, None, 1e9, sector)


def test_caps_open_risk_and_sector():
    t = at(DAY, "10:00")
    names = {k: _nd(k, [100.0] * 400, sector="IT") for k in "abcd"}
    taken, skips, _ = BK.run([_cand(k, t, rank=(r,)) for k, r in zip("abcd", (1, 4, 3, 2))],
                             names, prior_daily_net=[])
    assert [x["instrument_key"] for x in taken] == ["b", "c", "d"]   # ranked, 3 open
    assert [(z.key, z.reason) for z in skips] == [("a", "CAP_OPEN_RISK")]
    names = {k: _nd(k, [100.0] * 400, sector=s) for k, s in zip("abcde", "XXXXY")}
    BK.BOOK_SAVE = dict(SP.BOOK)
    try:
        SP.BOOK.update(max_open=10, open_risk_cap=1.0)
        taken, skips, _ = BK.run([_cand(k, t) for k in "abcde"], names, prior_daily_net=[])
    finally:
        SP.BOOK.clear()
        SP.BOOK.update(BK.BOOK_SAVE)
    assert {z.reason for z in skips} == {"CAP_SECTOR"} and len(taken) == 4


def test_daily_halt_after_minus_3pct():
    t1, t2 = at(DAY, "10:00"), at(DAY, "11:00")
    crash = [100.0] * 45 + [100.0] + [90.0] * 300          # a 10 % fall: three stops gap
    names = {k: _nd(k, crash) for k in "abc"}
    names["d"] = _nd("d", [100.0] * 400)
    c = [_cand(k, t1, stop=99.0, target=102.0) for k in "abc"] + [_cand("d", t2)]
    taken, skips, _ = BK.run(c, names, prior_daily_net=[])
    assert len(taken) == 3 and all(x["exit_reason"] == "STOP_GAP" for x in taken)
    assert [(z.key, z.reason) for z in skips] == [("d", "HALT_DAILY")]


# ── strategies ────────────────────────────────────────────────────────────────────
def _s1_name(vol_today=2000.0, close2=103.0, or_low=99.0):
    hist, dates = [], []
    for d in PREV:
        rows = [(100, 101, 99, 100, 1000.0)] * 25
        hist += _m15(d, rows)
        dates += [d] * 25
    today = [(100, 102, or_low, 101, 1000.0), (101, 102.5, 100.5, 102, 1000.0),
             (102, 103.5, 101.8, close2, vol_today)] + [(103, 103.2, 102.8, 103, 500.0)] * 22
    m15 = hist + _m15(DAY, today)
    m1 = _m1(DAY, [101.0] * 45 + [103.1] * 330)
    return NameDay("K", m1, m15, dates + [DAY] * 25, 101.0, 95.0, 15.0, 1e9, "IT")


def test_s1_breakout_rules():
    nifty = _m1(DAY, [100.0] + [101.0] * 374)
    br = {at(DAY, "09:45"): 0.7, at(DAY, "10:00"): 0.7}
    c = ST.orb_breadth(_s1_name(), DAY, nifty, br)       # target 102 + 3: RRR < 1.5
    assert isinstance(c, ST.Skip) and c.reason == "SKIP_RRR" and c.detail["rrr"] < 1.5
    c = ST.orb_breadth(_s1_name(or_low=95.0), DAY, nifty, br)   # width 7: target 109
    assert isinstance(c, ST.Candidate) and c.side == 1 and c.entry_raw == 103.1
    assert c.target == 109 and c.stop == pytest.approx(min(102, 103.1 - c.atr))
    assert c.signal_at == at(DAY, "10:00") and c.time_stop == at(DAY, "15:15")
    assert c.rrr >= 1.5 and c.checklist["p6_rrr"]
    # volume below the 10-session slot average: no signal at all
    assert ST.orb_breadth(_s1_name(vol_today=900.0), DAY, nifty, br) is None
    # breadth not above 60 %: no signal
    assert ST.orb_breadth(_s1_name(), DAY, nifty, {k: 0.5 for k in br}) is None


def test_s1_reads_nothing_after_the_signal():
    nifty = _m1(DAY, [100.0] + [101.0] * 374)
    br = {at(DAY, "09:45"): 0.7}
    a, b = _s1_name(), _s1_name()
    b.m15 = b.m15[:-20] + [IBar(x.start, x.end, 1, 500, 0.5, 400, 9e9) for x in b.m15[-20:]]
    b.m1 = b.m1[:46] + [IBar(x.start, x.end, 1, 1, 1, 1, 1) for x in b.m1[46:]]
    ra, rb = ST.orb_breadth(a, DAY, nifty, br), ST.orb_breadth(b, DAY, nifty, br)
    assert type(ra) is type(rb)
    if isinstance(ra, ST.Candidate):
        assert (ra.stop, ra.target, ra.entry_raw) == (rb.stop, rb.target, rb.entry_raw)


def test_checklist_and_rrr_verdict():
    t = at(DAY, "10:00")
    c = ST.Candidate("s", "K", 1, t, t, 100.0, 98.0, 102.0, 2.0, t, "EOD", 1.0,
                     {"p1_pattern": True, "p2_structure_stop": True, "p3_volume": True,
                      "p4_dow": True, "p5_indicators": False, "p6_rrr": False}, (1,))
    assert ST._verdict(c, ("p1_pattern", "p3_volume", "p6_rrr")).reason == "SKIP_RRR"
    c.checklist["p3_volume"] = False
    assert ST._verdict(c, ("p1_pattern", "p3_volume", "p6_rrr")).reason == "CHECKLIST_LT4"


# ── placebo ───────────────────────────────────────────────────────────────────────
def test_placebo_is_seeded_and_never_reuses_a_real_name():
    t = at(DAY, "10:00")
    names = {}
    for k in [f"N{i}" for i in range(30)]:
        nd = _s1_name()
        nd.key = k
        names[k] = nd
    real = [BK.trade_row(_cand("N0", t, entry=103.1, stop=101.1, target=107.1),
                         names["N0"], 100,
                         F.Path(t + _dt.timedelta(minutes=5), 101.1, "STOP"),
                         placebo=False, guard_flags=[])]
    real[0]["atr"] = 2.0
    real[0]["signal_at"] = at(DAY, "09:45")
    p1 = BK.placebo(real, names, list(names), "s", DAY)
    p2 = BK.placebo(real, names, list(names), "s", DAY)
    assert p1 and [x["instrument_key"] for x in p1] == [x["instrument_key"] for x in p2]
    assert p1[0]["instrument_key"] != "N0" and p1[0]["is_placebo"] is True
    assert p1[0]["evidence"]["mirror_of"] == "N0"


def test_spec_sha_is_stable():
    assert SP.spec_sha256() == SP.spec_sha256() and len(SP.spec_sha256()) == 64


def _s2_name(drop=97.5, prev_close=99.5, adx1d=15.0, vol=1500.0):
    hist, dates = [], []
    for d in PREV:
        rows = [(100, 100.6, 99.4, 100 + (0.05 if i % 2 else -0.05), 1000.0) for i in range(25)]
        hist += _m15(d, rows)
        dates += [d] * 25
    today = [(100, 100.6, 99.4, 100, 1000.0)] * 2 + [(100, 100.2, drop - 0.2, drop, vol)] \
        + [(drop, drop + 0.3, drop - 0.3, drop, 1000.0)] * 22
    m15 = hist + _m15(DAY, today)
    m1 = _m1(DAY, [100.0] * 30 + [(100, 100, drop, drop)] * 15 + [drop + 0.05] * 330)
    return NameDay("K", m1, m15, dates + [DAY] * 25, prev_close, None, adx1d, 1e9, "IT")


def test_s2_reversion_rules():
    c = ST.vwap_revert(_s2_name(), DAY)
    assert isinstance(c, ST.Candidate) and c.side == 1
    assert c.signal_at == at(DAY, "10:00") and c.entry_raw == pytest.approx(97.55)
    assert c.stop == pytest.approx(97.55 - c.atr) and c.target == pytest.approx(c.evidence["bb_mid"])
    assert c.time_stop == at(DAY, "11:00") and c.time_reason == "TIME_NOT_WORKING"
    # a trending stock (ADX 1d >= 20): no signal
    assert ST.vwap_revert(_s2_name(adx1d=25.0), DAY) is None
    # a move >= 3 % from the previous close is information, not noise
    z = ST.vwap_revert(_s2_name(prev_close=101.0), DAY)
    assert isinstance(z, ST.Skip) and z.reason == "MOVE_GT_3PCT"
    # volume below the slot average fails mandatory checklist point 3
    z = ST.vwap_revert(_s2_name(vol=500.0), DAY)
    assert isinstance(z, ST.Skip) and z.reason == "CHECKLIST_LT4"
