"""Dashboard analysis: pure functions, no database (user request 2026-10-22).

Everything here is RESEARCH, PAPER ONLY, and never investment advice. The rules are fixed,
transparent and listed with their reasons on the page, so a reader can see why a label
was given. Nothing here places, modifies or cancels an order.

  candles(bars)            per-candle anatomy and pattern names (rule based)
  trend(feat)              trend / momentum read of the Stage 3 features
  research_signal(...)     BULLISH / NEUTRAL / BEARISH research label with every reason
  ranges(...)              typical ranges: E5's q10-q90 for the next session, ATR for 5 days
  forensic(...)            fundamentals red / green flags
  cap_buckets(caps)        SEBI/AMFI rank buckets: 1-100 large, 101-250 mid, rest small
"""

from __future__ import annotations

import math
from typing import Any

SIGNAL_VERSION = "dash-signal-v1"
DISCLAIMER = ("Research signal from fixed rules and an unvalidated model (E5 forward test "
              "in progress). Paper research only - not investment advice; no order is "
              "ever placed.")


def _f(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


# ── candles ───────────────────────────────────────────────────────────────────────
def candles(bars: list[dict[str, Any]], vol_window: int = 20) -> list[dict[str, Any]]:
    """bars: oldest first, each {date, open, high, low, close, volume}. Returns one record per
    bar: body/wick shares, change, volume vs its trailing average and pattern names."""
    out = []
    for i, b in enumerate(bars):
        o, h, lo, c = (_f(b.get(k)) for k in ("open", "high", "low", "close"))
        v = _f(b.get("volume"))
        rec: dict[str, Any] = {"date": b["date"], "patterns": []}
        if None in (o, h, lo, c) or h < lo or o <= 0:
            out.append(rec)
            continue
        rng = h - lo
        body = abs(c - o)
        up = h - max(o, c)
        dn = min(o, c) - lo
        prev = bars[i - 1] if i else None
        pc = _f(prev.get("close")) if prev else None
        rec.update(change=None if not pc else c / pc - 1,
                   body_share=body / rng if rng else 0.0,
                   upper_wick_share=up / rng if rng else 0.0,
                   lower_wick_share=dn / rng if rng else 0.0,
                   direction="UP" if c > o else "DOWN" if c < o else "FLAT")
        past = [_f(x.get("volume")) for x in bars[max(0, i - vol_window):i]]
        past = [x for x in past if x]
        rec["volume_vs_avg"] = v / (sum(past) / len(past)) if v and past else None
        p = rec["patterns"]
        if rng and body <= 0.1 * rng:
            p.append("DOJI")
        if rng and body > 0 and dn >= 2 * body and up <= 0.3 * body + 0.05 * rng:
            p.append("HAMMER" if c >= o else "HANGING_MAN")
        if rng and body > 0 and up >= 2 * body and dn <= 0.3 * body + 0.05 * rng:
            p.append("SHOOTING_STAR" if c <= o else "INVERTED_HAMMER")
        if rng and body >= 0.9 * rng:
            p.append("MARUBOZU_UP" if c > o else "MARUBOZU_DOWN")
        if prev:
            po, ph, pl = (_f(prev.get(k)) for k in ("open", "high", "low"))
            if None not in (po, ph, pl, pc):
                if c > o and pc < po and c >= po and o <= pc:
                    p.append("BULLISH_ENGULFING")
                if c < o and pc > po and c <= po and o >= pc:
                    p.append("BEARISH_ENGULFING")
                if lo > ph:
                    p.append("GAP_UP")
                if h < pl:
                    p.append("GAP_DOWN")
                if h <= ph and lo >= pl:
                    p.append("INSIDE_BAR")
        if rec["volume_vs_avg"] and rec["volume_vs_avg"] >= 2:
            p.append("VOLUME_SPIKE")
        out.append(rec)
    return out


# ── trend and the research signal ───────────────────────────────────────────────────
def trend(feat: dict[str, Any]) -> dict[str, Any]:
    """feat: Stage 3 feature values of one stock (None when missing)."""
    c20, c50, c200 = (_f(feat.get(k)) for k in ("close_to_sma_20", "close_to_sma_50",
                                               "close_to_sma_200"))
    rsi = _f(feat.get("rsi_14"))
    if c50 is None:
        label = "UNKNOWN"
    elif c50 > 0 and (c200 is None or c200 > 0) and (c20 is None or c20 > 0):
        label = "UPTREND"
    elif c50 < 0 and (c200 is None or c200 < 0) and (c20 is None or c20 < 0):
        label = "DOWNTREND"
    else:
        label = "SIDEWAYS"
    mom = ("OVERBOUGHT" if rsi is not None and rsi >= 75 else
           "OVERSOLD" if rsi is not None and rsi <= 25 else
           "STRONG" if rsi is not None and rsi >= 55 else
           "WEAK" if rsi is not None and rsi <= 45 else
           "NEUTRAL" if rsi is not None else "UNKNOWN")
    return {"trend": label, "momentum": mom, "rsi_14": rsi, "close_to_sma_20": c20,
            "close_to_sma_50": c50, "close_to_sma_200": c200}


def research_signal(feat: dict[str, Any], e5: dict[str, Any] | None = None,
                    picked: bool = False) -> dict[str, Any]:
    """BULLISH (score >= 3) / BEARISH (<= -3) / NEUTRAL, with every contribution listed."""
    reasons: list[tuple[str, float]] = []

    def add(why: str, pts: float) -> None:
        reasons.append((why, pts))

    t = trend(feat)
    for k, name in (("close_to_sma_20", "20-day"), ("close_to_sma_50", "50-day"),
                    ("close_to_sma_200", "200-day")):
        v = t[k]
        if v is not None:
            add(f"price {'above' if v > 0 else 'below'} its {name} average ({v:+.1%})",
                1.0 if v > 0 else -1.0)
    rsi = t["rsi_14"]
    if rsi is not None:
        if rsi >= 75:
            add(f"RSI {rsi:.0f}: overbought (pullback risk)", -0.5)
        elif rsi <= 25:
            add(f"RSI {rsi:.0f}: oversold (bounce possible, trend weak)", 0.5)
        elif rsi >= 55:
            add(f"RSI {rsi:.0f}: positive momentum", 1.0)
        elif rsi <= 45:
            add(f"RSI {rsi:.0f}: negative momentum", -1.0)
    mh = _f(feat.get("macd_histogram"))
    if mh is not None and mh != 0:
        add(f"MACD histogram {'positive' if mh > 0 else 'negative'}", 0.5 if mh > 0 else -0.5)
    sent = _f(feat.get("mnews_company_sentiment_3d"))
    if sent is not None and abs(sent) >= 0.2:
        add(f"news tone last 3 days {'positive' if sent > 0 else 'negative'} ({sent:+.2f})",
            1.0 if sent > 0 else -1.0)
    if e5:
        pu, er = _f(e5.get("prob_up")), _f(e5.get("exp_return"))
        if picked:
            add("in today's E5 model picks (unvalidated model)", 1.0)
        elif pu is not None and pu >= 0.55:
            add(f"E5 model: P(up) {pu:.0%}", 0.5)
        elif pu is not None and pu <= 0.45:
            add(f"E5 model: P(up) {pu:.0%}", -0.5)
        if er is not None and abs(er) >= 0.003:
            add(f"E5 model: expected open-close {er:+.2%}", 0.5 if er > 0 else -0.5)
    score = sum(p for _, p in reasons)
    label = "BULLISH" if score >= 3 else "BEARISH" if score <= -3 else "NEUTRAL"
    return {"label": label, "score": round(score, 2), "version": SIGNAL_VERSION,
            "reasons": [{"why": w, "points": p} for w, p in reasons],
            "trend": t["trend"], "momentum": t["momentum"], "disclaimer": DISCLAIMER}


def ranges(close: float | None, atr_pct: float | None,
           e5: dict[str, Any] | None = None) -> dict[str, Any]:
    """Typical ranges, never a target: E5's q10-q90 of the next session's open-to-close,
    and close x (1 +- ATR% x sqrt(5)) for about a week (1 ATR is a typical day's range)."""
    out: dict[str, Any] = {"basis": "typical range, not a target"}
    c, a = _f(close), _f(atr_pct)
    if c and a:
        w = a * math.sqrt(5)
        out["five_day"] = {"low": c * (1 - w), "high": c * (1 + w), "width_pct": w}
    if e5 and c:
        lo, hi = _f(e5.get("range_lo")), _f(e5.get("range_hi"))
        if lo is not None and hi is not None:
            out["next_session_q10_q90"] = {"low": c * (1 + lo), "high": c * (1 + hi),
                                           "lo_pct": lo, "hi_pct": hi}
    return out


# ── forensic ──────────────────────────────────────────────────────────────────────
def forensic(ratios: dict[str, Any], holdings: list[dict[str, Any]] | None,
             feat: dict[str, Any]) -> dict[str, Any]:
    """Red / green flags from the fundamentals Prajna holds (vendor snapshots)."""
    red, green = [], []
    pe = _f(ratios.get("pe_company"))
    pe_sec = _f(ratios.get("pe_sector"))
    if pe_sec is not None and (pe_sec > 150 or pe_sec <= 0):
        red.append(f"sector P/E {pe_sec:g} from the vendor looks implausible: not compared")
        pe_sec = None
    if pe is not None and pe < 0:
        red.append("negative earnings (P/E < 0)")
    elif pe is not None and pe_sec and pe > 2 * pe_sec:
        red.append(f"P/E {pe:.1f} more than twice the sector's {pe_sec:.1f}")
    elif pe is not None and pe_sec and 0 < pe < 0.7 * pe_sec:
        green.append(f"P/E {pe:.1f} below the sector's {pe_sec:.1f}")
    roe = _f(ratios.get("roe"))
    if roe is not None and roe >= 15:
        green.append(f"ROE {roe:.1f}%")
    elif roe is not None and roe < 5:
        red.append(f"ROE {roe:.1f}%")
    lta = _f(feat.get("liabilities_to_assets"))
    if lta is not None and lta > 0.8:
        red.append(f"liabilities {lta:.0%} of assets")
    for k, name in (("pat_yoy", "yearly profit"), ("pat_yoy_q", "quarterly profit")):
        v = _f(feat.get(k))
        if v is not None and v <= -0.3:
            red.append(f"{name} down {v:.0%} year on year")
        elif v is not None and v >= 0.3:
            green.append(f"{name} up {v:+.0%} year on year")
    s = _f(feat.get("eps_surprise_srw"))
    if s is not None:
        (green if s > 0 else red).append(f"latest EPS vs a year ago: {s:+.2f}")
    for h in holdings or []:
        hist = [x for x in h.get("history") or [] if _f(x.get("value")) is not None]
        if len(hist) >= 2 and h.get("category") in ("promoters", "pledge", "pledged"):
            now_, before = _f(hist[0]["value"]), _f(hist[-1]["value"])
            d = now_ - before
            if h["category"] == "promoters" and d <= -2:
                red.append(f"promoter holding down {d:.1f} pp "
                           f"({hist[-1]['period']} -> {hist[0]['period']})")
            elif h["category"] == "promoters" and d >= 2:
                green.append(f"promoter holding up {d:+.1f} pp")
            elif h["category"] != "promoters" and now_ and now_ > 10:
                red.append(f"pledged shares {now_:.1f}%")
    return {"red_flags": red, "green_flags": green,
            "basis": "vendor fundamentals snapshots held by Prajna; not an audit"}


def cap_buckets(caps: dict[str, float]) -> dict[str, str]:
    """SEBI/AMFI rank rule: 1-100 LARGE, 101-250 MID, the rest SMALL (by market cap)."""
    order = sorted((k for k, v in caps.items() if v and v > 0), key=lambda k: -caps[k])
    return {k: "LARGE" if i < 100 else "MID" if i < 250 else "SMALL"
            for i, k in enumerate(order)}


# ── trade plan (user 2026-10-22: "buy karna hai ya sell, target T1 T2, kab") ─────────────
PLAN_VERSION = "dash-plan-v1"
ACTIONS = {"BULLISH": "BUY", "NEUTRAL": "HOLD / WAIT", "BEARISH": "SELL / AVOID"}
PLAN_DISCLAIMER = ("Rule-based plan from fixed technical rules (ATR, 20-day support and "
                   "resistance, moving averages) and an unvalidated model. Not validated, "
                   "not investment advice; paper research only - no order is ever placed.")


def levels(bars: list[dict[str, Any]]) -> dict[str, float | None]:
    """Support / resistance from the daily bars (oldest first; today's may be included)."""
    def ext(n, k, f):
        xs = [_f(b.get(k)) for b in bars[-n:]]
        xs = [x for x in xs if x is not None]
        return f(xs) if xs else None
    return {"support_20": ext(20, "low", min), "resistance_20": ext(20, "high", max),
            "swing_low_60": ext(60, "low", min), "swing_high_60": ext(60, "high", max),
            "high_252": ext(252, "high", max), "low_252": ext(252, "low", min)}


def _sma(close: float, c2s: float | None) -> float | None:
    return close / (1 + c2s) if c2s is not None and c2s > -1 else None


def trade_plan(close: float | None, feat: dict[str, Any], lv: dict[str, Any],
               signal: dict[str, Any]) -> dict[str, Any]:
    """BUY / HOLD-WAIT / SELL-AVOID with entry zone, stop-loss, T1 (1.5R), T2 (3R) and the
    conditions to act, from fixed rules. R = entry - stop."""
    c = _f(close)
    if not c:
        return {"action": None, "why": "no price"}
    atr_pct = _f(feat.get("atr_pct_14")) or 0.02
    atr = atr_pct * c
    s20, r20 = _f(lv.get("support_20")), _f(lv.get("resistance_20"))
    hi252 = _f(lv.get("high_252"))
    sma20 = _sma(c, _f(feat.get("close_to_sma_20")))
    sma50 = _sma(c, _f(feat.get("close_to_sma_50")))
    action = ACTIONS.get(signal.get("label"), "HOLD / WAIT")
    rnd = lambda x: None if x is None else round(x, 2)  # noqa: E731
    basis = [f"ATR(14) = {atr:.2f} ({atr_pct:.1%} of price)"]

    def stop_below(entry: float) -> float:
        structural = (s20 - 0.25 * atr) if s20 is not None else None
        if structural is None or structural >= entry - atr or structural <= entry - 3 * atr:
            basis.append("stop = entry - 1.5 x ATR (the 20-day low is too near or too far)")
            return entry - 1.5 * atr
        basis.append(f"stop = 20-day low {s20:.2f} - 0.25 x ATR")
        return structural

    plan: dict[str, Any] = {"action": action, "version": PLAN_VERSION, "price": rnd(c)}
    if action == "BUY":
        lo = max(c - 0.5 * atr, sma20) if sma20 and sma20 < c else c - 0.5 * atr
        entry = (lo + c) / 2
        sl = stop_below(entry)
        r = entry - sl
        t1, t2 = entry + 1.5 * r, entry + 3 * r
        plan.update(entry_zone=[rnd(lo), rnd(c)], entry=rnd(entry), stop_loss=rnd(sl),
                    t1=rnd(t1), t2=rnd(t2), risk_per_share=rnd(r),
                    reward_risk="T1 1.5 : 1, T2 3 : 1")
        plan["when_buy"] = [f"in the entry zone {lo:.2f} - {c:.2f} while the price stays above "
                            + (f"its 20-day average ({sma20:.2f})" if sma20 else "the stop"),
                            *([f"or on a daily close above the 20-day high {r20:.2f} (breakout)"]
                              if r20 and r20 > c else [])]
        plan["when_sell"] = [f"stop-loss: exit on a daily close below {sl:.2f}",
                             f"T1 {t1:.2f}: book part, move the stop to the entry {entry:.2f}",
                             f"T2 {t2:.2f}: book the rest"
                             + (f", or exit on a daily close below the 50-day average "
                                f"({sma50:.2f})" if sma50 else "")]
        if r20 and entry < r20 < t1:
            plan["when_sell"].append(f"first resistance on the way: the 20-day high {r20:.2f}")
        if hi252 and t1 < hi252 < t2:
            plan["when_sell"].append(f"52-week high {hi252:.2f} lies between T1 and T2")
    elif action == "SELL / AVOID":
        bounce = min(x for x in (sma20, c + 0.5 * atr) if x is not None and x > c) \
            if (sma20 and sma20 > c) else c + 0.5 * atr
        r = 1.5 * atr
        t1, t2 = c - r, c - 2 * r
        plan.update(exit_zone=[rnd(c), rnd(bounce)], stop_loss=rnd(c + r), t1=rnd(t1),
                    t2=rnd(t2), risk_per_share=rnd(r), reward_risk="downside levels 1R and 2R")
        basis.append("downside levels: price - 1.5 x ATR and - 3 x ATR")
        plan["when_sell"] = [f"if holding: exit now or on a bounce into {c:.2f} - {bounce:.2f}",
                             f"downside levels if the fall continues: {t1:.2f}, then {t2:.2f}"
                             + (f" (20-day low {s20:.2f})" if s20 else "")]
        plan["when_buy"] = ["avoid new buying while the signal is SELL / AVOID",
                            "reconsider only after a daily close above "
                            + (f"the 50-day average ({sma50:.2f})" if sma50 else
                               f"{c + r:.2f}") + " or when the signal turns BUY"]
    else:
        trig = r20 if r20 and r20 > c else c + 0.5 * atr
        sl = stop_below(trig)
        r = trig - sl
        t1, t2 = trig + 1.5 * r, trig + 3 * r
        hold_sl = max(x for x in (s20, c - 2 * atr) if x is not None)
        plan.update(buy_trigger=rnd(trig), stop_loss=rnd(sl), t1=rnd(t1), t2=rnd(t2),
                    risk_per_share=rnd(r), holding_stop=rnd(hold_sl),
                    reward_risk="T1 1.5 : 1, T2 3 : 1 from the trigger")
        plan["when_buy"] = [f"wait: buy only on a daily close above {trig:.2f} "
                            + ("(the 20-day high, a breakout)" if trig == r20 else ""),
                            f"then stop {sl:.2f}, T1 {t1:.2f}, T2 {t2:.2f}"]
        plan["when_sell"] = [f"if holding: keep with a stop at {hold_sl:.2f}",
                             "exit if the signal turns SELL / AVOID"]
    plan["basis"] = [*basis, f"signal {signal.get('label')} (score {signal.get('score')}, "
                     f"{signal.get('version')})", "T1 = entry + 1.5 R, T2 = entry + 3 R"]
    plan["disclaimer"] = PLAN_DISCLAIMER
    return plan


MEANING = {
    "BULLISH_ENGULFING": "bullish reversal sign (buyers took over the previous candle)",
    "BEARISH_ENGULFING": "bearish reversal sign (sellers took over the previous candle)",
    "HAMMER": "possible bottom: sellers pushed down, buyers closed it near the high",
    "HANGING_MAN": "warning after a rise: long lower shadow at a high",
    "SHOOTING_STAR": "possible top: buyers pushed up, sellers closed it near the low",
    "INVERTED_HAMMER": "possible bottom attempt (needs a strong next candle)",
    "DOJI": "indecision: buyers and sellers balanced",
    "MARUBOZU_UP": "strong buying all session", "MARUBOZU_DOWN": "strong selling all session",
    "GAP_UP": "opened above the previous high (strong demand)",
    "GAP_DOWN": "opened below the previous low (strong supply)",
    "INSIDE_BAR": "range contraction: a breakout either way may follow",
    "VOLUME_SPIKE": "volume at least 2 x its 20-day average (the move has participation)"}


def candle_read(candles_: list[dict[str, Any]], trend_: str | None, n: int = 5
                ) -> list[str]:
    """Plain-language reading of the last n candles' patterns."""
    out = []
    for c in candles_[-n:][::-1]:
        for p in c.get("patterns") or []:
            out.append(f"{c['date']}: {p.replace('_', ' ').lower()} - {MEANING.get(p, '')}")
    if trend_:
        out.append(f"overall trend: {trend_.lower()} (price vs its 20/50/200-day averages)")
    return out
