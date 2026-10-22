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


def test_trade_plan_levels_follow_the_rules():
    f = {"atr_pct_14": 0.02, "close_to_sma_20": 0.05, "close_to_sma_50": 0.08}
    lv = {"support_20": 90.0, "resistance_20": 104.0, "high_252": 120.0}
    buy = A.trade_plan(100.0, f, lv, {"label": "BULLISH", "score": 4, "version": "v"})
    assert buy["action"] == "BUY" and buy["entry_zone"] == [99.0, 100.0]
    r = buy["entry"] - buy["stop_loss"]
    assert buy["stop_loss"] == pytest.approx(99.5 - 1.5 * 2.0)        # 20-day low too far
    assert buy["t1"] == pytest.approx(buy["entry"] + 1.5 * r, abs=0.01)
    assert buy["t2"] == pytest.approx(buy["entry"] + 3 * r, abs=0.01)
    assert any("breakout" in x for x in buy["when_buy"]) and "not investment advice" in \
        buy["disclaimer"]
    near = A.trade_plan(100.0, f, {**lv, "support_20": 96.5}, {"label": "BULLISH"})
    assert near["stop_loss"] == pytest.approx(96.5 - 0.25 * 2.0)        # structural stop
    sell = A.trade_plan(100.0, f, lv, {"label": "BEARISH"})
    assert sell["action"] == "SELL / AVOID" and sell["t1"] == 97.0 and sell["t2"] == 94.0
    assert sell["stop_loss"] == 103.0 and "avoid new buying" in sell["when_buy"][0]
    wait = A.trade_plan(100.0, f, lv, {"label": "NEUTRAL"})
    assert wait["action"] == "HOLD / WAIT" and wait["buy_trigger"] == 104.0
    assert wait["holding_stop"] == 96.0                                   # max(90, 100 - 4)
    assert A.trade_plan(None, f, lv, {"label": "BULLISH"})["action"] is None


def test_live_indicators_use_the_stage3_definitions():
    import datetime as dt

    from app.dashboard import indicators as IND
    from app.features.compute import Bar
    from app.features.compute import price as PR
    hist = [Bar(dt.date(2026, 1, 1) + dt.timedelta(days=i), 100 + i, 101 + i, 99 + i,
                100.5 + i, 1000) for i in range(260)]
    q = {"ltp": 380.0, "open": 361.0, "high": 381.0, "low": 359.0, "volume": 5000,
         "date": "2026-12-31"}
    out = IND.compute(hist, q)
    bars = [*hist, Bar(dt.date(2026, 12, 31), 361.0, 381.0, 359.0, 380.0, 5000)]
    assert out["rsi_14"] == PR.rsi(bars, 14)[0]
    assert out["close_to_sma_50"] == PR.close_to_sma(bars, 50)[0]
    assert out["ret_1d"] == pytest.approx(380.0 / 359.5 - 1)
    assert IND.compute([], q) == {} and IND.compute(hist, {"ltp": None}) == {}


def test_market_report_validation_and_themes():
    from app.dashboard import report as RP
    item = {"headline": "h", "text": "t", "impact": "i"}
    good = {"title": "T", "indian_market": [item], "global_market": [],
            "variables_to_monitor": ["crude"], "overall": "o"}
    assert RP.validate("noise " + json.dumps(good) + " noise") == good
    for bad in ({**good, "extra": 1}, {**good, "indian_market": [{"headline": "h"}]},
                {**good, "overall": "We recommend you buy banks."}):
        with pytest.raises(ValueError):
            RP.validate(json.dumps(bad))
    th = RP.themes([{"title": "Brent crude jumps", "publisher": "Mint"},
                    {"title": "RBI minutes hint at hikes", "publisher": "BL"},
                    {"title": "Nothing here", "publisher": "X"}])
    assert set(th) == {"crude_commodities", "rbi_rates_bonds"}
    rec = {"status": "OK", "date": "2026-10-22", "generated_at": "2026-10-22T16:20:00",
           "report": {**good, "indian_market": [item]}}
    assert "not a trading recommendation" in RP.telegram_text(rec)


async def test_us10y_from_the_treasury_csv(monkeypatch):
    import datetime as dt

    import httpx

    from app.dashboard import macro_ext as MX
    csv_text = ('Date,"1 Mo","10 Yr","30 Yr"\n10/21/2026,4.09,5.13,5.42\n'
                "10/20/2026,4.10,5.12,5.40\n")
    t = httpx.MockTransport(lambda req: httpx.Response(200, text=csv_text))
    async with httpx.AsyncClient(transport=t) as c:
        x = await MX.us10y(c, dt.date(2026, 10, 22))
    assert (x["ltp"], x["change_bps"], x["date"]) == (5.13, 1.0, "2026-10-21")
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    async with httpx.AsyncClient(transport=t) as c:
        assert await MX.broad_dollar(c, dt.date(2026, 10, 22)) is None   # no key: not shown


def test_bhavcopy_official_close_replaces_the_last_trade():
    import datetime as dt
    import io
    import zipfile

    from app.dashboard import bhav as BH
    head = ("TradDt,TckrSymb,SctySrs,ISIN,OpnPric,HghPric,LwPric,ClsPric,LastPric,"
            "PrvsClsgPric,TtlTradgVol\n")
    row = "2026-10-22,REPL,EQ,INE364Z01019,68.00,78.69,67.22,77.68,78.69,65.58,630609\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("b.csv", head + row)
    b = BH.parse(buf.getvalue(), dt.date(2026, 10, 22))["NSE_EQ|INE364Z01019"]
    assert (b["close"], b["last"], b["prev_close"]) == (77.68, 78.69, 65.58)
    q = {"ltp": 78.69, "prev_close": 65.58, "change": .1999, "open": 68, "high": 78.69,
         "low": 67.22, "date": "2026-10-22"}
    a = BH.apply(q, b)
    assert a["ltp"] == 77.68 and a["last_trade"] == 78.69 and a["official_close"]
    assert a["change"] == pytest.approx(77.68 / 65.58 - 1)


def _b(d, o, h, lo, c):
    return {"date": d, "open": o, "high": h, "low": lo, "close": c}


def test_forward_record_evaluation_rules():
    from app.dashboard import signals_log as SL
    buy = {"key": "k", "day": "2026-10-22", "action": "BUY", "price": 100.0, "entry": 99.0,
           "stop_loss": 96.0, "t1": 103.5, "t2": 108.0, "signal_score": 4}
    ev = lambda bars: SL.evaluate([buy], {"k": bars})[0]["outcome"]  # noqa: E731
    assert ev([])["status"] == "WAITING"
    assert ev([_b("2026-10-23", 101, 102, 100, 101)] * 10)["status"] == "NOT_FILLED"
    # filled, then stop and target on the same later bar: the stop (conservative)
    s = ev([_b("2026-10-23", 100, 100.5, 98.5, 99.5), _b("2026-10-26", 99, 104, 95, 100)])
    assert s["status"] == "STOP" and s["r"] == -1.0
    # T1 then T2: 0.5 x 1.5R + 0.5 x 3R = 2.25R
    t = ev([_b("2026-10-23", 100, 104, 98, 103), _b("2026-10-26", 103, 109, 102, 108)])
    assert t["status"] == "T2" and t["r"] == pytest.approx(2.25)
    # T1, then back to the entry: half booked at 1.5R -> 0.75R
    be = ev([_b("2026-10-23", 100, 104, 98, 103), _b("2026-10-26", 103, 103, 98.9, 99)])
    assert be["status"] == "T1_THEN_ENTRY_STOP" and be["r"] == pytest.approx(0.75)
    # a bar of the plan's own day is never used
    assert ev([_b("2026-10-22", 100, 120, 90, 100)])["status"] == "WAITING"
    view = {"key": "k", "day": "2026-10-22", "action": "SELL / AVOID", "price": 100.0,
            "stop_loss": 103.0, "t1": 97.0, "t2": 94.0, "signal_score": -4}
    v = SL.evaluate([view], {"k": [_b(f"2026-10-2{i}", 99, 99.5, 96.5, 97) for i in
                                   range(3, 8)]})[0]["outcome"]
    assert v["status"] == "DOWNSIDE_1" and v["ret"] == pytest.approx(-0.03) and v["complete"]
    st = SL.stats(SL.evaluate([buy, view], {"k": [_b("2026-10-23", 100, 104, 98, 103),
                                                  _b("2026-10-26", 103, 109, 102, 108)]}))
    assert st["buy"]["closed"] == 1 and st["buy"]["win_rate"] == 1.0


def test_forward_record_is_written_once(tmp_path, monkeypatch):
    import datetime as dt

    from app.dashboard import signals_log as SL
    monkeypatch.setattr(SL, "DIR", tmp_path)
    plans = [{"key": "a", "action": "BUY", "entry": 1}, {"key": "b", "action": "HOLD / WAIT"},
             {"key": "c", "action": "SELL / AVOID"}]
    assert SL.write(dt.date(2026, 10, 22), plans)["written"] == 2       # HOLD not recorded
    assert SL.write(dt.date(2026, 10, 22), plans[:1])["exists"]          # never rewritten
    assert [r["key"] for r in SL.load()] == ["a", "c"]


def test_alert_events_and_once_a_day(tmp_path, monkeypatch):
    import datetime as dt

    from app.dashboard import alerts as AL
    buy = {"action": "BUY", "entry": 99.0, "stop_loss": 96.0, "t1": 103.5, "t2": 108.0}
    assert [e for e, _ in AL.events(buy, 95.0)] == ["STOP"]
    assert [e for e, _ in AL.events(buy, 104.0)] == ["T1"]
    assert [e for e, _ in AL.events(buy, 108.5)] == ["T2"]
    assert [e for e, _ in AL.events(buy, 98.5)] == ["ENTRY_ZONE"]
    assert AL.events(buy, 101.0) == [] and AL.events(None, 1.0) == []
    assert [e for e, _ in AL.events({"action": "HOLD / WAIT", "buy_trigger": 50}, 51)] == \
        ["BREAKOUT"]
    assert [e for e, _ in AL.events({"action": "SELL / AVOID", "stop_loss": 110, "t1": 90},
                                    89)] == ["DOWNSIDE_1"]
    monkeypatch.setattr(AL, "SENT", tmp_path / "alerts")
    monkeypatch.setattr(AL, "BASE", tmp_path)
    monkeypatch.setattr(AL, "WATCH", tmp_path / "w.json")
    d = dt.date(2026, 10, 23)
    assert AL.due(d, [("a", "x"), ("b", "y")]) == [("a", "x"), ("b", "y")]
    assert AL.due(d, [("a", "x"), ("c", "z")]) == [("c", "z")]            # a: already sent
    assert AL.set_watch("tcs", True) == ["TCS"] and AL.set_watch("TCS", False) == []


def test_official_close_change_uses_the_adjusted_previous_close():
    from app.dashboard import bhav as BH
    b = {"close": 302.2, "last": 302.0, "prev_close": 2994.8, "open": 300.0, "high": 305.0,
         "low": 298.0}
    q = {"ltp": 302.0, "prev_close": 299.48, "change": 0.008}
    assert BH.apply(q, b)["change"] == pytest.approx(302.2 / 299.48 - 1)   # not -89.9 %
    assert BH.apply({"ltp": 1.0}, b)["change"] == pytest.approx(302.2 / 2994.8 - 1)
