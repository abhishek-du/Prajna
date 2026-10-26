"""Regime engine v0 (pre-registration §4): pre-session features from daily bars <= T - 1,
the open gap from the first 1m bar, intraday breadth at the checkpoints, a first-match
rule table and the recorded risk multiplier. PURE: the job loads the inputs."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from app.shadow import indicators as I
from app.shadow.bars import IBar, NameDay, at, last_until
from app.shadow.spec import REGIME as R

LOOKBACK = 300


def _tail(s: dict[str, list], d: int, n: int = LOOKBACK) -> dict[str, list[float]]:
    """The valid (all fields > 0) daily bars of sessions < d, newest last, at most n."""
    out: dict[str, list[float]] = {"high": [], "low": [], "close": []}
    for i in range(max(0, d - n), d):
        v = [s[f][i] for f in ("high", "low", "close")]
        if all(x is not None and x > 0 for x in v):
            for f, x in zip(("high", "low", "close"), v):
                out[f].append(float(x))
    return out


def _last(x: Sequence[float | None]) -> float | None:
    return x[-1] if x else None


def index_trend(s: dict[str, list], d: int) -> dict[str, Any]:
    t = _tail(s, d)
    c = t["close"]
    if len(c) < 2 * R["adx_n"] + 1 or len(c) < R["ema_trend"]:
        return {"adx14": None, "above_ema50": None, "close": _last(c)}
    a = _last(I.adx(t["high"], t["low"], c, R["adx_n"]))
    e = _last(I.ema(c, R["ema_trend"]))
    return {"adx14": a, "above_ema50": None if e is None else c[-1] > e, "close": c[-1],
            "ema50": e}


def pre_features(idx: dict[str, dict[str, list]], eq: dict[str, dict[str, list]],
                 universe: list[str], d: int, *, results_share: float,
                 calendar_events: list[str], holiday_thin: bool) -> dict[str, Any]:
    """idx: 'nifty', 'bank', 'vix' daily series on the Market's session axis; eq: the
    universe's daily series; d: the index of session T on that axis."""
    nifty, bank = index_trend(idx["nifty"], d), index_trend(idx["bank"], d)
    nc = _tail(idx["nifty"], d)["close"]
    rets = [nc[i] / nc[i - 1] - 1 for i in range(1, len(nc))]
    sig = None
    if len(rets) >= R["sigma_n"]:
        w = rets[-R["sigma_n"]:]
        mu = sum(w) / len(w)
        sig = math.sqrt(sum((r - mu) ** 2 for r in w) / (len(w) - 1))
    vc = _tail(idx["vix"], d)["close"]
    vix_pct = vix_chg = None
    if len(vc) >= R["vix_pct_n"]:
        w = vc[-R["vix_pct_n"]:]
        vix_pct = sum(1 for x in w if x <= vc[-1]) / len(w)
    if len(vc) >= 2:
        vix_chg = vc[-1] / vc[-2] - 1
    above = n50 = adv = dec = nh = nl = 0
    for k in universe:
        c = [x for x in eq[k]["close"][max(0, d - 60):d] if x is not None and x > 0]
        if len(c) >= R["sma_breadth"]:
            n50 += 1
            above += c[-1] > sum(c[-R["sma_breadth"]:]) / R["sma_breadth"]
        if len(c) >= 2:
            adv += c[-1] > c[-2]
            dec += c[-1] < c[-2]
        if len(c) >= R["nh_nl_n"]:
            w = c[-R["nh_nl_n"]:]
            nh += c[-1] >= max(w)
            nl += c[-1] <= min(w)
    n = len(universe)
    return {
        "nifty_adx14": nifty["adx14"], "bank_adx14": bank["adx14"],
        "nifty_above_ema50": nifty["above_ema50"], "bank_above_ema50": bank["above_ema50"],
        "breadth_50dma": above / n50 if n50 else None,
        "ad_ratio": adv / (adv + dec) if adv + dec else None,
        "nh_nl_20": (nh - nl) / n if n else None,
        "vix_close": _last(vc), "vix_pct252": vix_pct, "vix_chg_1d": vix_chg,
        "nifty_sigma20": sig, "nifty_ret_1d": rets[-1] if rets else None,
        "results_share": results_share, "calendar_events": sorted(calendar_events),
        "holiday_thin": holiday_thin, "universe": n,
    }


def classify(f: dict[str, Any]) -> tuple[str, str, float]:
    """(state, rule fired, risk multiplier). A missing input never satisfies a rule; the
    fall-through is MIXED (stand aside)."""
    def ge(x, y):
        return x is not None and x >= y

    sig, r1 = f.get("nifty_sigma20"), f.get("nifty_ret_1d")
    shock = [n for n, ok in (
        ("vix_pct252>=0.90", ge(f.get("vix_pct252"), R["vix_pct_shock"])),
        ("vix_chg_1d>=+20%", ge(f.get("vix_chg_1d"), R["vix_jump"])),
        ("|nifty_ret_1d|>=2sigma20", sig is not None and r1 is not None
         and abs(r1) >= R["sigma_shock"] * sig),
        ("ad_ratio<=0.2", f.get("ad_ratio") is not None and f["ad_ratio"] <= R["ad_collapse"]),
    ) if ok]
    if shock:
        state, rule = "SHOCK", "1:" + ",".join(shock)
    elif f.get("calendar_events") or ge(f.get("results_share"), R["results_share_event"]):
        state, rule = "EVENT_WAIT", "2:" + ",".join(
            list(f.get("calendar_events") or [])
            + (["results_share>=5%"] if ge(f.get("results_share"), R["results_share_event"])
               else []))
    elif (ge(f.get("nifty_adx14"), R["adx_trend"]) and f.get("nifty_above_ema50") is True
          and f.get("bank_above_ema50") is True
          and f.get("breadth_50dma") is not None and f["breadth_50dma"] > R["breadth_up"]):
        state, rule = "TREND_UP", "3:adx>=25,both>ema50,breadth>60%"
    elif (ge(f.get("nifty_adx14"), R["adx_trend"]) and f.get("nifty_above_ema50") is False
          and f.get("bank_above_ema50") is False
          and f.get("breadth_50dma") is not None and f["breadth_50dma"] < R["breadth_down"]):
        state, rule = "TREND_DOWN", "4:adx>=25,both<ema50,breadth<40%"
    elif f.get("nifty_adx14") is not None and f["nifty_adx14"] < R["adx_range"]:
        state, rule = "RANGE", "5:adx<20"
    else:
        state, rule = "MIXED", "6:otherwise"
    mult = R["mult"][state]
    if f.get("holiday_thin"):
        mult *= R["holiday_thin_mult"]
    return state, rule, mult


def open_features(nifty_1m: list[IBar], prev_close: float | None,
                  sigma20: float | None) -> dict[str, Any]:
    if not nifty_1m or not prev_close:
        return {"nifty_open": None, "nifty_gap": None, "nifty_gap_sigma": None,
                "shock_open": False}
    o = nifty_1m[0].open
    g = o / prev_close - 1
    gs = g / sigma20 if sigma20 else None
    return {"nifty_open": o, "nifty_gap": g, "nifty_gap_sigma": gs,
            "shock_open": gs is not None and abs(gs) >= R["sigma_shock"]}


def breadth_at(names: dict[str, NameDay], t) -> dict[str, float | None]:
    """Shares of the universe above its own open / session VWAP / previous close, from
    the 1m bars knowable at t (end <= t)."""
    ab_o = ab_v = up = dn = n = 0
    for nd in names.values():
        bars = [b for b in nd.m1 if b.end <= t]
        if not bars:
            continue
        n += 1
        last = bars[-1].close
        ab_o += last > bars[0].open
        vw = I.vwap([b.high for b in bars], [b.low for b in bars], [b.close for b in bars],
                    [b.volume for b in bars])[-1]
        ab_v += vw is not None and last > vw
        if nd.prev_close:
            up += last > nd.prev_close
            dn += last < nd.prev_close
    return {"breadth_above_open": ab_o / n if n else None,
            "breadth_above_vwap": ab_v / n if n else None,
            "ad_ratio_intraday": up / (up + dn) if up + dn else None, "names_seen": n}


def intraday_features(session, hhmm: str, nifty_1m: list[IBar],
                      names: dict[str, NameDay]) -> dict[str, Any]:
    t = at(session, hhmm)
    b = last_until(nifty_1m, t)
    nfo = None
    if b is not None and nifty_1m:
        nfo = b.close / nifty_1m[0].open - 1
    return {"nifty_from_open": nfo, **breadth_at(names, t)}


def day_type(f: dict[str, Any]) -> str:
    x, br = f.get("nifty_from_open"), f.get("breadth_above_open")
    if x is None:
        return "UNCLEAR"
    if x >= R["day_trend_from_open"] and br is not None and br >= R["day_trend_breadth"]:
        return "TREND_DAY_UP"
    if x <= -R["day_trend_from_open"] and br is not None and br <= 1 - R["day_trend_breadth"]:
        return "TREND_DAY_DOWN"
    if abs(x) < R["day_range_from_open"]:
        return "RANGE_DAY"
    return "UNCLEAR"
