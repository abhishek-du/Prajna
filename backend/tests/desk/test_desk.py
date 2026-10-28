"""Research Desk: the rule judge, attribution, the validator and retry, conflicts, watchlist
transitions, the live tracker and the store (fake model, synthetic dossiers)."""

from __future__ import annotations

import datetime as _dt
import json
import os

import pytest
from sqlalchemy import text

from app.desk import config as K
from app.desk import dossier as DS
from app.desk import investigate as INV
from app.desk import rules as RJ
from app.desk import track as TR
from app.desk import watchlist as WL

UTC = _dt.UTC
TOKEN = os.environ.get("PRAJNA_WRITE_TOKEN", "test-token-not-a-real-secret")


def _px(**kw):
    base = {"close": 100.0, "atr_pct": 0.02, "close_to_sma_20": 0.02, "close_to_sma_50": 0.03,
            "close_to_sma_200": 0.05, "rsi_14": 60.0, "macd_histogram": 0.1, "ret_1d": 0.01,
            "support_20": 95.0, "resistance_20": 104.0, "swing_low_60": 90.0,
            "swing_high_60": 106.0, "high_252": 120.0, "low_252": 80.0}
    return {**base, **kw}


EX = {"median_turnover": 5e8, "upper_circuit": 120.0, "lower_circuit": 80.0}


# ── rule judge ──────────────────────────────────────────────────────────────────────
def test_rule_judge_clean_buy_has_cost_aware_rrr():
    r = RJ.judge(_px(), EX, {"news_24h": 0})
    assert r["decision"] == "BUY" and r["flags"] == []
    assert r["cost"]["net_rrr_t1"] < r["cost"]["gross_rrr_t1"]
    s = r["cost"]["slippage_scenarios_bps"]
    assert s["5"] > s["10"] > s["20"]


def test_rule_judge_hilinfra_like_case():
    """+20 % day at the upper circuit, 5.9 ATR above the 20-day average, illiquid, news."""
    px = _px(close=73.83, atr_pct=0.052, close_to_sma_20=0.4389, rsi_14=88.0, ret_1d=0.1999,
             support_20=41.55, resistance_20=73.83)
    r = RJ.judge(px, {"median_turnover": 3.6e6, "upper_circuit": 73.83, "lower_circuit": 49.2},
                 {"news_24h": 2, "bad_data": ["recent listing"]})
    assert {"CIRCUIT_UPPER", "EXTENDED", "ILLIQUID", "NEWS_MOVE", "BAD_DATA"} <= set(r["flags"])
    assert r["decision"] == "AVOID" and r["extension_atr"] > 5


def test_rule_judge_extended_buy_becomes_watch_with_pullback():
    r = RJ.judge(_px(close_to_sma_20=0.08, atr_pct=0.02), EX, {"news_24h": 0})
    assert "EXTENDED" in r["flags"] and r["decision"] == "WATCH"
    assert r["plan"]["pullback_entry"] == pytest.approx(100 / 1.08 + 2.0, abs=0.01)


# ── dossier helpers ─────────────────────────────────────────────────────────────────
def test_attribution_and_beta():
    a = DS.attribution(0.05, 1.2, 0.01, 0.02)
    assert a["market_part"] == pytest.approx(0.012) and a["sector_part"] == pytest.approx(0.008)
    assert a["stock_part"] == pytest.approx(0.03) and a["main_driver"] == "stock_specific"
    ix = [100 * (1.01 if i % 2 else 0.995) ** i for i in range(80)]
    sr = [2 * x for x in ix]                                     # moves 1:1 with the index
    assert DS.beta(sr, ix, 79) == pytest.approx(1.0, abs=1e-6)
    assert DS.beta(sr[:10], ix[:10], 9) is None


def test_price_facts_on_a_series():
    n = 260
    c = [100 + i * 0.1 for i in range(n)]
    sr = {"open": c, "high": [x + 1 for x in c], "low": [x - 1 for x in c], "close": c,
          "volume": [1000.0] * (n - 1) + [3000.0]}
    f = DS.price_facts(sr, n - 1)
    assert f["close"] == c[-1] and f["ret_1d"] == pytest.approx(c[-1] / c[-2] - 1)
    assert f["volume_x20"] == pytest.approx(3.0) and f["close_to_sma_20"] > 0
    assert f["support_20"] == min(x - 1 for x in c[-20:])
    assert DS.price_facts({k: v[:10] for k, v in sr.items()}, 9) is None


# ── validator / investigator ────────────────────────────────────────────────────────
def _packet(rule_decision="BUY", flags=()):
    return {"stock": {"symbol": "TST"}, "evidence": {
        "px": {"close": 100.0, "atr_pct": 0.02}, "lvl": {"support_20": 95.0},
        "attr": {"ret": 0.01}, "exec": {"median_turnover": 1e9}, "ctx": {"x": 1},
        "fund": {"p/e": 20}, "rule": {"decision": rule_decision, "flags": list(flags)},
        "news": [{"id": "news:7"}], "res": [], "ca": []}}


def _answer(**kw):
    a = {"why_moved": {"summary": "s", "driver": "STOCK_NEWS", "evidence_ids": ["news:7"]},
         "pov": {p: 60 for p in K.POVS}, "score": 75, "decision": "BUY", "horizon": "INTRADAY",
         "entry_lo": 99.0, "entry_hi": 100.0, "stop": 97.5, "t1": 103.0, "t2": 106.0,
         "levels_basis": {"entry": "e", "stop": "s", "targets": "t"}, "thesis": "th",
         "risks": ["r"], "invalidation": "below 97", "rule_disagreement": None,
         "evidence_ids": ["px", "lvl", "news:7"]}
    return {**a, **kw}


@pytest.mark.parametrize("change, why", [
    ({"decision": "MAYBE"}, "decision"),
    ({"score": 140}, "score"),
    ({"evidence_ids": ["news:999"], "why_moved": {"evidence_ids": []}}, "unknown evidence"),
    ({"evidence_ids": [], "why_moved": {}}, "no evidence"),
    ({"stop": 101.0}, "not ordered"),
    ({"t1": None}, "BUY needs"),
    ({"stop": 99.4, "entry_lo": 99.5}, "ATR from the entry"),
    ({"thesis": ""}, "thesis"),
])
def test_validator_rejects(change, why):
    st, reason = INV.validate(_answer(**change), _packet())
    assert st == "INVALID" and why in reason


def test_validator_accepts_and_watch_needs_no_levels():
    assert INV.validate(_answer(), _packet()) == ("OK", None)
    w = _answer(decision="WATCH", entry_lo=None, entry_hi=None, stop=None, t1=None, t2=None)
    assert INV.validate(w, _packet())[0] == "OK"


def test_conflicts_record_llm_overrides():
    assert INV.conflicts(_answer(), {"decision": "AVOID", "flags": ["CIRCUIT_UPPER"]}) == [
        "LLM_BUY_vs_RULE_CIRCUIT_UPPER", "LLM_BUY_vs_RULE_AVOID"]
    assert INV.conflicts(_answer(decision="AVOID"), {"decision": "BUY", "flags": []}) == [
        "LLM_AVOID_vs_RULE_BUY"]
    assert INV.conflicts(_answer(), {"decision": "BUY", "flags": []}) == []


class FakeModel:
    def __init__(self, answers):
        self.answers, self.prompts = list(answers), []

    async def __call__(self, model_id, prompt):
        self.prompts.append(prompt)
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return (a if isinstance(a, str) else json.dumps(a)), "v1"


async def test_investigate_retries_once_then_ok():
    m = FakeModel([_answer(score=300), _answer()])
    v = await INV.investigate(m, _packet(rule_decision="AVOID", flags=["EXTENDED"]))
    assert v["status"] == "OK" and len(m.prompts) == 2 and "invalid" in m.prompts[1]
    assert v["decision"] == "BUY" and v["score"] == 75 and v["entry_lo"] == 99.0
    assert v["conflicts"] == ["LLM_BUY_vs_RULE_EXTENDED", "LLM_BUY_vs_RULE_AVOID"]
    assert "news:7" in v["evidence_ids"] and len(v["prompt_sha256"]) == 64


async def test_investigate_errors_and_invalid():
    v = await INV.investigate(FakeModel([RuntimeError("throttled")] * 2), _packet())
    assert v["status"] == "ERROR" and "throttled" in v["invalid_reason"]
    v = await INV.investigate(FakeModel(["not json at all", "still not"]), _packet())
    assert v["status"] == "INVALID" and v["conflicts"] == [] and v["evidence_ids"] == []


# ── watchlist / tracker (pure) ──────────────────────────────────────────────────────
def _v(i, k, dec="BUY", score=80, status="OK"):
    return {"id": i, "instrument_key": k, "symbol": k, "status": status, "decision": dec,
            "score": score}


def test_watchlist_transitions():
    act = {"A": {"verdict_id": 1, "score": 80, "decision": "BUY"},
           "B": {"verdict_id": 2, "score": 75, "decision": "BUY"},
           "C": {"verdict_id": 3, "score": 72, "decision": "BUY"},
           "D": {"verdict_id": 4, "score": 72, "decision": "BUY"}}
    ev = WL.transitions(act, [_v(10, "A", score=85), _v(11, "B", dec="AVOID", score=30),
                              _v(12, "N", score=72), _v(13, "M", score=60),
                              _v(14, "Q", dec="WATCH", score=90), _v(15, "Z", status="INVALID")],
                        sessions_since={"C": 5, "D": 2}, ended={"D": "STOP"})
    got = {(e["instrument_key"], e["event"]) for e in ev}
    assert got == {("A", "UPDATE"), ("B", "REMOVE"), ("N", "ADD"), ("C", "REMOVE"),
                   ("D", "REMOVE")}
    assert next(e for e in ev if e["instrument_key"] == "D")["reason"] == "stop-loss hit"


def test_tracker_evaluate_paths():
    v = {"entry_lo": 99, "entry_hi": 100, "stop": 97, "t1": 103, "t2": 106, "horizon": "INTRADAY"}
    t = _dt.datetime(2026, 10, 28, 5, 0, tzinfo=UTC)            # 10:30 IST
    assert TR.evaluate(v, set(), 101.5, t) == []
    assert TR.evaluate(v, set(), 99.6, t) == ["ENTRY_TRIGGERED"]
    assert TR.evaluate(v, set(), 96.0, t) == ["INVALIDATED"]
    on = {"ENTRY_TRIGGERED"}
    assert TR.evaluate(v, on, 103.2, t) == ["T1"]
    assert TR.evaluate(v, on, 107.0, t) == ["T1", "T2"]
    assert TR.evaluate(v, on | {"T1"}, 96.9, t) == ["STOP"]
    late = _dt.datetime(2026, 10, 28, 9, 50, tzinfo=UTC)        # 15:20 IST
    assert TR.evaluate(v, on, 101.0, late) == ["EXPIRED"]
    assert TR.evaluate(v, {"ENTRY_TRIGGERED", "STOP"}, 110.0, t) == []
    assert TR.evaluate({**v, "horizon": "SWING_1_5D"}, on, 101.0, late) == []


# ── database ────────────────────────────────────────────────────────────────────────
@pytest.mark.db
@pytest.mark.integration
async def test_run_store_watchlist_and_tracking(db_session, monkeypatch):
    from app.desk import run as DR
    day = _dt.date(2026, 10, 28)

    async def fake_build(s, session, mode, **kw):
        return {"universe": 1, "dossiers": {"NSE_EQ|TST": {
            "packet": _packet(rule_decision="BUY"), "sha": "a" * 64, "symbol": "TST"}}}
    monkeypatch.setattr(DR.DS, "build", fake_build)
    with pytest.raises(Exception, match="token"):
        await DR.execute(db_session, day, "EVENING", FakeModel([_answer()]), commit=True,
                         token="wrong", code_git_sha="t")
    swing = _answer(horizon="SWING_1_5D")          # no 15:15 expiry whatever the clock says
    res = await DR.execute(db_session, day, "EVENING", FakeModel([swing]), commit=True,
                           token=TOKEN, code_git_sha="t")
    assert res["status"] == "WRITTEN" and res["counts"]["mix"] == {"BUY": 1}
    assert [e["event"] for e in res["watchlist_events"]] == ["ADD"]
    act = await WL.active(db_session)
    assert list(act) == ["NSE_EQ|TST"] and float(act["NSE_EQ|TST"]["t1"]) == 103.0
    at = _dt.datetime.now(UTC) + _dt.timedelta(minutes=1)
    prices = iter([99.8, 103.5, 96.5])
    for _ in range(3):
        p = next(prices)
        await TR.tick(db_session, lambda k, p=p: {"ltp": p}, at)
    kinds = list((await db_session.execute(text("""select kind from desk_track_event
        order by id"""))).scalars())
    assert kinds == ["ENTRY_TRIGGERED", "T1", "STOP"]
    assert await WL.active(db_session) == {}
    last = (await db_session.execute(text("""select event, reason from desk_watch_event
        order by id desc limit 1"""))).one()
    assert tuple(last) == ("REMOVE", "stop-loss hit")
    with pytest.raises(Exception, match="append-only"):
        await db_session.execute(text("update desk_verdict set score = 1"))
    await db_session.rollback()


def test_summary_render():
    from app.desk import summary as SM
    txt = SM.render({"status": "WRITTEN", "mode": "EVENING", "session": "2026-10-28",
                     "counts": {"investigated": 3, "mix": {"BUY": 1, "AVOID": 2},
                                "conflicts": 1},
                     "watchlist_events": [{"event": "ADD", "symbol": "TST", "decision": "BUY",
                                           "score": 80}]})
    assert "Investigated 3: AVOID 2, BUY 1" in txt and "TST (BUY 80)" in txt
    assert SM.render({"status": "DRY_RUN"}) == ""


def test_stock_page_plan_v2_guards():
    feat = {"close_to_sma_20": 0.4389, "close_to_sma_50": 0.53, "close_to_sma_200": 0.46,
            "rsi_14": 88.0, "macd_histogram": 0.5, "atr_pct_14": 0.052}
    lv = {"support_20": 41.55, "resistance_20": 73.83, "swing_low_60": 40.1,
          "swing_high_60": 73.83, "high_252": 82.88, "low_252": 40.1}
    p = RJ.stock_plan(72.18, feat, lv, {"median_turnover": 3.6e6, "upper_circuit": 73.83,
                                        "day_high": 73.83}, {"news_24h": 2, "ret_1d": 0.173})
    assert p["action"] == "AVOID" and p["v1_action"] == "BUY" and p["version"] == "dash-plan-v2"
    assert {"CIRCUIT_TOUCHED", "EXTENDED", "ILLIQUID", "NEWS_MOVE"} <= set(p["guards"])
    assert p["when_buy"][0].startswith("avoid new buying")
    ext = RJ.stock_plan(108.0, {**feat, "close_to_sma_20": 0.08, "rsi_14": 65.0,
                                "atr_pct_14": 0.02}, {**lv, "support_20": 100.0,
                                                     "resistance_20": 109.0},
                        {"median_turnover": 5e8}, {"news_24h": 0, "ret_1d": 0.01})
    assert ext["action"] == "HOLD / WAIT" and ext["when_buy"][0].startswith("wait for a pullback")
    ok = RJ.stock_plan(100.0, {**feat, "close_to_sma_20": 0.02, "rsi_14": 60.0,
                               "atr_pct_14": 0.02}, {**lv, "support_20": 95.0,
                                                    "resistance_20": 104.0},
                       {"median_turnover": 5e8}, {"news_24h": 0, "ret_1d": 0.01})
    assert ok["action"] == "BUY" and ok["guards"] == [] and ok["cost"]["net_rrr_t1"] < 1.5


def test_forensic_skips_an_implausible_sector_pe():
    from app.dashboard import analysis as A
    f = A.forensic({"pe_company": 11.9, "pe_sector": 194.65}, [], {})
    assert not any("below the sector" in g for g in f["green_flags"])
    assert any("implausible" in r for r in f["red_flags"])


def test_list_action_uses_the_v2_guards():
    feat = {"close_to_sma_20": 0.44, "close_to_sma_50": 0.53, "close_to_sma_200": 0.46,
            "rsi_14": 70.0, "macd_histogram": 0.5, "atr_pct_14": 0.05, "turnover_20": 3.6e6}
    act, guards = RJ.list_action(72.18, feat, {"upper_circuit": 73.83, "high": 73.83}, 0.17)
    assert act == "AVOID" and {"CIRCUIT_TOUCHED", "ILLIQUID", "EXTENDED"} <= set(guards)
    ok = {**feat, "close_to_sma_20": 0.02, "turnover_20": 5e8, "rsi_14": 60.0, "atr_pct_14": 0.02}
    assert RJ.list_action(100.0, ok, None, 0.01) == ("BUY", [])
    assert RJ.list_action(None, ok, None, None) == (None, [])


def test_cited_field_ids_cite_their_block():
    from app.desk.investigate import cited_ids
    raw = {"evidence_ids": ["attr.main_driver", "fund.p/e", "ctx.regime.state", "news:12.title",
                            "px", "execution"],
           "why_moved": {"evidence_ids": ["exec.median_turnover", "rule_flags"]}}
    assert cited_ids(raw) == {"attr", "fund", "ctx", "news:12", "px", "execution", "exec",
                              "rule"}
