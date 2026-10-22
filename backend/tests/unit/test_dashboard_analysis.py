"""Dashboard analysis rules (pure) and the AI note's validation: patterns, trend, the
research signal's score and reasons, ranges (never a target), forensic flags, cap
buckets, and refusal of advice / price targets in the model's answer."""

from __future__ import annotations

import json

import pytest

from app.dashboard import ai_summary as AIS
from app.dashboard import analysis as A


def bar(d, o, h, lo, c, v=100):
    return {"date": d, "open": o, "high": h, "low": lo, "close": c, "volume": v}


def test_candle_patterns():
    bars = [bar("d1", 100, 101, 95, 96),
            bar("d2", 95, 103, 94.5, 102.5),            # bullish engulfing
            bar("d3", 102, 110, 101.8, 102.1),
            bar("d4", 111, 111.5, 110.5, 111.02, 500),  # doji, gap up, volume spike
            bar("d5", 111.1, 111.4, 110.6, 111.0)]      # inside bar
    c = A.candles(bars)
    assert "BULLISH_ENGULFING" in c[1]["patterns"]
    assert "DOJI" in c[3]["patterns"] and "GAP_UP" in c[3]["patterns"]
    assert "VOLUME_SPIKE" in c[3]["patterns"]
    assert "INSIDE_BAR" in c[4]["patterns"]
    assert c[1]["change"] == pytest.approx(102.5 / 96 - 1)
    assert A.candles([bar("x", None, 1, 1, 1)])[0]["patterns"] == []          # malformed


def test_hammer():
    c = A.candles([bar("a", 100, 101, 99, 100.5), bar("b", 100, 100.6, 96, 100.5)])
    assert "HAMMER" in c[1]["patterns"]


def test_signal_scores_and_reasons():
    bull = {"close_to_sma_20": .02, "close_to_sma_50": .05, "close_to_sma_200": .1,
            "rsi_14": 60, "macd_histogram": .5, "mnews_company_sentiment_3d": .4}
    s = A.research_signal(bull, {"prob_up": .6, "exp_return": .004}, picked=True)
    assert s["label"] == "BULLISH" and s["trend"] == "UPTREND"
    assert s["score"] == pytest.approx(3 + 1 + .5 + 1 + 1 + .5)
    assert all(r["why"] for r in s["reasons"]) and "not investment advice" in s["disclaimer"]
    bear = {k: -abs(v) for k, v in bull.items() if k != "rsi_14"} | {"rsi_14": 40}
    assert A.research_signal(bear)["label"] == "BEARISH"
    assert A.research_signal({})["label"] == "NEUTRAL"
    over = A.research_signal({"rsi_14": 80})
    assert over["reasons"][0]["points"] == -0.5 and over["momentum"] == "OVERBOUGHT"


def test_ranges_are_ranges_not_targets():
    r = A.ranges(100.0, 0.02, {"range_lo": -0.01, "range_hi": 0.015})
    assert r["basis"] == "typical range, not a target"
    assert r["next_session_q10_q90"] == pytest.approx(
        {"low": 99.0, "high": 101.5, "lo_pct": -0.01, "hi_pct": 0.015})
    assert r["five_day"]["width_pct"] == pytest.approx(0.02 * 5 ** 0.5)
    assert A.ranges(None, None) == {"basis": "typical range, not a target"}


def test_forensic_flags():
    hold = [{"category": "promoters", "history": [{"value": 45.0, "period": "Jun 2026"},
                                                  {"value": 50.0, "period": "Sep 2025"}]}]
    f = A.forensic({"pe_company": 80, "pe_sector": 20, "roe": 3}, hold,
                   {"liabilities_to_assets": .9, "pat_yoy": -.5})
    red = " ".join(f["red_flags"])
    assert "twice the sector" in red and "ROE 3.0%" in red and "promoter holding down" in red
    assert "liabilities 90%" in red and "yearly profit down" in red
    g = A.forensic({"pe_company": 10, "pe_sector": 20, "roe": 22}, [], {"pat_yoy_q": .5})
    assert len(g["green_flags"]) == 3 and not g["red_flags"]


def test_cap_buckets_rank_rule():
    caps = {f"k{i}": float(1000 - i) for i in range(300)} | {"none": 0.0}
    b = A.cap_buckets(caps)
    assert b["k0"] == "LARGE" and b["k99"] == "LARGE" and b["k100"] == "MID"
    assert b["k249"] == "MID" and b["k250"] == "SMALL" and "none" not in b


GOOD = {"summary": "Steady quarter.", "positives": ["a"], "risks": ["b"], "watch": ["c"]}


def test_ai_note_validation():
    assert AIS.validate(json.dumps(GOOD)) == GOOD
    assert AIS.validate("```json\n" + json.dumps(GOOD) + "\n```") == GOOD
    for bad in ({**GOOD, "extra": 1}, {**GOOD, "risks": "x"},
                {**GOOD, "summary": "We recommend you buy it."},
                {**GOOD, "watch": ["a price target of 1500"]}):
        with pytest.raises(ValueError):
            AIS.validate(json.dumps(bad))


def test_live_quote_parse_and_overlay():
    from app.dashboard import live as LV
    v = {"instrument_token": "NSE_EQ|X", "last_price": 216.49, "net_change": -4.41,
         "ohlc": {"open": 216.49, "high": 216.49, "low": 216.49, "close": 216.49},
         "volume": 28801, "last_trade_time": "1792665305062",
         "lower_circuit_limit": 216.49, "upper_circuit_limit": 225.31}
    q = LV.parse(v)
    assert q["key"] == "NSE_EQ|X" and q["prev_close"] == pytest.approx(220.9)
    assert q["change"] == pytest.approx(216.49 / 220.9 - 1) and q["date"] == "2026-10-22"
    assert LV.parse({"instrument_token": "k"}) is None                 # no price: no quote
    row = {"close": 220.9, "day_change": -0.09, "close_date": "2026-10-21", "x": 1}
    o = LV.overlay(row, q)
    assert (o["close"], o["close_date"], o["price_basis"]) == (216.49, "2026-10-22",
                                                               "live (Upstox quote)")
    assert row["close"] == 220.9 and LV.overlay(row, None) is row       # a copy; none: as is
