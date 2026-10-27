"""The intraday Buy List: picks, the 1-minute grading, the summary and the Telegram text."""

from __future__ import annotations

import datetime as _dt

import pytest

from app.lab import buylist as BL
from app.lab import telegram_ai as TG
from app.lab.forensic import Bar

UTC = _dt.UTC
DAY = _dt.date(2026, 10, 28)


def _bars(path):
    """path: [(open, high, low, close)] per minute from 09:15 IST."""
    t0 = _dt.datetime(2026, 10, 28, 3, 45, tzinfo=UTC)
    return [Bar(t0 + _dt.timedelta(minutes=i), t0 + _dt.timedelta(minutes=i + 1), h, lo, c, o)
            for i, (o, h, lo, c) in enumerate(path)]


PX = {"close": 100.0, "atr_pct": 0.02, "rsi_14": 60.0, "ret_1d": 0.01, "ret_5d": 0.02}
RULE_BUY = {"decision": "BUY", "flags": [], "signal": {"score": 4.5},
            "plan": {"entry_zone": [99.0, 100.0], "stop_loss": 97.0, "t1": 103.0, "t2": 106.0}}
DESK_BUY = {"decision": "BUY", "score": 80, "entry_lo": 99.5, "entry_hi": 100.5, "stop": 98.0,
            "t1": 104.0, "t2": 108.0, "why_moved": {"summary": "order win"}}


def test_item_sources_and_rank():
    r = BL.item("K", {"symbol": "TST"}, PX, RULE_BUY, None)
    assert r["levels_from"] == "RULES" and r["swing_plan"]["t1"] == 103.0
    assert r["t1"] == pytest.approx(101.5) and r["stop"] == pytest.approx(99.0)   # intraday ATR
    assert r["t2"] == pytest.approx(102.0) == r["typical_high"] and r["rr_t1"] == pytest.approx(1.5)
    d = BL.item("K", {"symbol": "TST"}, PX, RULE_BUY, DESK_BUY)
    assert d["levels_from"] == "DESK" and d["agree"] and d["swing_plan"]["t1"] == 104.0
    assert BL.item("K", {}, PX, {**RULE_BUY, "decision": "WATCH"}, None) is None
    w = BL.item("K", {}, PX, {**RULE_BUY, "decision": "WATCH"}, DESK_BUY)
    assert w["levels_from"] == "DESK" and not w["agree"]
    assert [x["symbol"] for x in BL.rank_items([r, d])] == ["TST", "TST"]
    assert BL.rank_items([r, d])[0]["agree"]


def test_grade_t1_stop_and_eod():
    # atr 4 %: from the 100 open the stop is 98, T1 103, T2 104
    it = {"symbol": "A", "key": "A", "atr_pct": 0.04, "prev_close": 99.0, "typical_high": 102.0}
    g = BL.grade_one(it, _bars([(100, 101, 99.5, 100.5), (100.5, 103.2, 100.4, 103)]), DAY)
    assert g["status"] == "T1" and g["exit"] == pytest.approx(103.0) and g["entry"] == 100
    assert g["net_pct"] == pytest.approx(0.03 - BL.COST) and g["reached_typical_high"]
    assert g["gap_pct"] == pytest.approx(100 / 99 - 1) and g["stop"] == pytest.approx(98.0)
    g = BL.grade_one(it, _bars([(100, 103.5, 97.5, 99)]), DAY)        # both in one bar: stop
    assert g["status"] == "STOP" and g["exit"] == pytest.approx(98.0)
    g = BL.grade_one(it, _bars([(100, 101, 99.5, 100.5), (100.5, 101.5, 100, 101)]), DAY)
    assert g["status"] == "EOD" and g["exit"] == 101
    assert BL.grade_one(it, [], DAY)["status"] == "NO_DATA"
    s = BL.summary([BL.grade_one(it, _bars([(100, 103.2, 99.9, 103)]), DAY),
                    BL.grade_one({**it, "symbol": "B", "agree": True},
                                 _bars([(100, 100.1, 97.0, 97.5)]), DAY), {"status": "NO_DATA"}])
    assert s["picks"] == 3 and s["graded"] == 2 and s["profitable"] == 1
    assert s["best"] == "A" and s["worst"] == "B" and s["t1_hit"] == 1 and s["stopped"] == 1


def test_telegram_templates_and_model_fallback():
    brief = {"session_date": DAY, "regime": {"state": "EVENT_WAIT", "note": "half size"},
             "events": {"calendar": ["FOMC"]}, "candidates": {"BUYLIST": [
                 BL.item("K", {"symbol": "TST", "sector": "IT"}, PX, RULE_BUY, DESK_BUY)]}}
    f = TG.morning_facts(brief)
    assert f["picks"][0]["symbol"] == "TST" and f["total_picks"] == 1
    t = TG.template_morning(f)
    assert "TST" in t and "🎯" in t and "Aaj ki Intraday Buy List" in t
    assert TG._sane("🟢 TST aaj BUY, T1 104", {"TST"})
    assert not TG._sane("🟢 FAKESTOCK aaj BUY", {"TST"})

    async def bad_model(mid, prompt):
        return "🟢 INVENTED stock 900% upar", None
    import asyncio
    out = asyncio.run(TG.write("MORNING", f, bad_model))
    assert "INVENTED" not in out and out.endswith(TG.DISCLAIMER)

    async def good_model(mid, prompt):
        assert "FACTS" in prompt
        return "☀️ Aaj ki Intraday Buy List\n🟢 TST entry 99.5-100.5 🎯 104", None
    out = asyncio.run(TG.write("MORNING", f, good_model))
    assert out.startswith("☀️") and "TST" in out and out.endswith(TG.DISCLAIMER)
    grade = {"happened": {"grades": [BL.grade_one({"symbol": "TST", "key": "K", "atr_pct": 0.04},
                                                  _bars([(100, 103.2, 99.9, 103)]),
                                                  DAY)], "summary": {"profitable": 1, "graded": 1,
                                                                     "t1_hit": 1, "stopped": 0,
                                                                     "eod": 0, "avg_net_pct": 0.027,
                                                                     "total_net_inr": 2700.0}}}
    e = TG.template_eod(TG.eod_facts(DAY, grade))
    assert "1/1 fayde mein" in e and "✅ TST T1" in e
