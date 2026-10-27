"""Strategy Lab: pure forensics, the switches, the store's run versioning, append-only tables,
the P1 SWITCHED_OFF skip, the brief's setups and the dashboard's write guard."""

from __future__ import annotations

import datetime as _dt
import os

import pytest
from sqlalchemy import text

from app.lab import forensic as F
from app.lab import registry as RG

UTC = _dt.UTC
T0 = _dt.datetime(2026, 10, 28, 4, 30, tzinfo=UTC)          # 10:00 IST


def _bars(prices: list[tuple[float, float, float]], start: _dt.datetime = T0) -> list[F.Bar]:
    out = []
    for i, (h, lo, c) in enumerate(prices):
        a = start + _dt.timedelta(minutes=i)
        out.append(F.Bar(a, a + _dt.timedelta(minutes=1), h, lo, c))
    return out


# ── pure ────────────────────────────────────────────────────────────────────────────
def test_excursion_long_with_target_after_exit():
    bars = _bars([(101, 99, 100), (103, 100, 102), (102, 97.5, 98), (99, 97, 98), (106, 98, 105)])
    exit_at = bars[2].end                                     # stopped in the third bar
    x = F.excursion(bars, 1, 100.0, bars[0].start, exit_at, stop=98.0, target=105.0)
    assert x["bars"] == 3
    assert x["mfe_pct"] == pytest.approx(0.03) and x["mae_pct"] == pytest.approx(0.025)
    assert x["mfe_r"] == pytest.approx(1.5) and x["mae_r"] == pytest.approx(1.25)
    assert x["target_after_exit"] is True


def test_excursion_short_and_empty():
    bars = _bars([(101, 99, 100), (100, 96, 97)])
    x = F.excursion(bars, -1, 100.0, bars[0].start, bars[1].end, stop=102.0, target=95.0)
    assert x["mfe_pct"] == pytest.approx(0.04) and x["mae_pct"] == pytest.approx(0.01)
    assert x["target_after_exit"] is None                     # no bar after the exit
    assert F.excursion([], 1, 100.0, T0, T0, 99.0)["mfe_pct"] is None


def test_index_move():
    bars = _bars([(1, 1, 100.0), (1, 1, 101.0), (1, 1, 99.0)])
    assert F.index_move(bars, bars[0].end, bars[2].end) == pytest.approx(-0.01)
    assert F.index_move(bars, T0, bars[2].end) is None


@pytest.mark.parametrize("t, cls", [
    ({"exit_reason": "TARGET", "net_inr": 10, "side": 1}, "TARGET_HIT"),
    ({"exit_reason": "STOP_GAP", "net_inr": -10, "side": 1}, "GAP_THROUGH_STOP"),
    ({"exit_reason": "STOP", "net_inr": -1, "side": 1, "news_after": [{"id": 1}]}, "NEWS_SHOCK"),
    ({"exit_reason": "STOP", "net_inr": -1, "side": 1, "target_after_exit": True},
     "STOPPED_IN_NOISE"),
    ({"exit_reason": "STOP", "net_inr": -1, "side": 1, "index_move": -0.004}, "MARKET_TURNED"),
    ({"exit_reason": "STOP", "net_inr": -1, "side": -1, "index_move": 0.004}, "MARKET_TURNED"),
    ({"exit_reason": "STOP", "net_inr": -1, "side": 1, "mfe_r": 1.2}, "GAVE_BACK"),
    ({"exit_reason": "STOP", "net_inr": -1, "side": 1}, "STOPPED"),
    ({"exit_reason": "EOD", "net_inr": 5, "side": 1}, "TIME_EXIT_WIN"),
    ({"exit_reason": "TIME_NOT_WORKING", "net_inr": -5, "side": 1}, "TIME_EXIT_LOSS"),
    ({"exit_reason": "CLOSE", "net_inr": 5, "side": 1}, "CLOSE_WIN"),
    ({"exit_reason": "CLOSE", "net_inr": -5, "side": 1, "mfe_pct": 0.02}, "GAVE_BACK"),
    ({"exit_reason": "CLOSE", "net_inr": -5, "side": 1, "index_move": -0.01}, "MARKET_AGAINST"),
    ({"exit_reason": "CLOSE", "net_inr": -5, "side": 1}, "CLOSE_LOSS"),
    ({"exit_reason": "NOT_FILLED", "net_inr": 0, "side": 1}, "NOT_FILLED"),
    ({"exit_reason": "OPEN_POSITION", "net_inr": 3, "side": 1}, "OPEN_GAIN"),
])
def test_classify(t, cls):
    got, rule = F.classify(t)
    assert got == cls and rule


def test_day_why_no_trade_and_misfit_and_placebo():
    w = F.day_why("orb_breadth_core_v1", [], regime_pre="RANGE", day_type="RANGE_DAY",
                  skips={"SKIP_RRR": 4, "CHECKLIST_LT4": 9})
    assert w[0]["code"] == "NO_TRADE_FILTERED" and "checklist under 4 of 6 (9)" in w[0]["en"]
    trades = [{"is_placebo": False, "exit_reason": "STOP", "net_inr": -500.0,
               "outcome_class": "STOPPED_IN_NOISE"},
              {"is_placebo": False, "exit_reason": "TARGET", "net_inr": 900.0,
               "outcome_class": "TARGET_HIT"},
              {"is_placebo": False, "exit_reason": "NOT_FILLED", "net_inr": 0.0,
               "outcome_class": "NOT_FILLED"}]
    w = F.day_why("orb_breadth_core_v1", trades, regime_pre="MIXED", day_type="RANGE_DAY",
                  placebo_net=100.0)
    codes = [x["code"] for x in w]
    assert "REGIME_MISFIT" in codes and "REGIME_CAUTION" in codes
    assert "MAIN_STOPPED_IN_NOISE" in codes
    res = next(x for x in w if x["code"] == "RESULT")
    assert res["en"].startswith("2 trades, 1 won")          # the unfilled order is not a trade
    assert next(x for x in w if x["code"] == "VS_PLACEBO")["en"].endswith("better.")
    assert F.day_why("vwap_revert_core_v1", [], regime_pre=None, day_type=None,
                     enabled=False)[0]["code"] == "SWITCHED_OFF"


def test_registry_defaults():
    assert set(RG.P1) == {"orb_breadth_core_v1", "orb_breadth_strict_v1",
                          "vwap_revert_core_v1", "vwap_revert_strict_v1"}
    assert not RG.BY_NAME["baseline_c0"].default_on
    assert "e5_ensemble" not in RG.SWITCHABLE


def test_brief_watch_setups():
    from app.lab import brief as B
    sym = {"symbol": "ABC", "sector": "X"}
    s1 = B.watch("k", sym, 100.0, {"ema50": 95.0, "adx14": 30.0, "atr_pct_1d": 0.02,
                                    "sr_zones": [110.0, 90.0]}, 60.0)
    assert [x["strategy"] for x in s1] == ["S1"] and s1[0]["side"] == 1
    assert s1[0]["zone"] == 110.0 and "trigger" in s1[0] and "invalidate" in s1[0]
    hot = B.watch("k", sym, 100.0, {"ema50": 95.0, "adx14": 30.0, "atr_pct_1d": 0.05,
                                     "sr_zones": []}, 60.0)
    assert hot == []                                          # ATR above 3 %: no S1
    s2 = B.watch("k", sym, 100.0, {"ema50": 99.0, "adx14": 15.0, "atr_pct_1d": 0.02,
                                    "sr_zones": [99.2, 120.0]}, 42.0)
    assert [(x["strategy"], x["side"]) for x in s2] == [("S2", 1)]


def test_brief_preopen_eligible_ranks_by_turnover_without_the_gap():
    from app.lab import brief as B
    n = 300
    good = {"close": [100.0] * n + [None], "volume": [1e6] * n + [None],
            "open": [100.0] * n + [None], "high": [101.0] * n + [None],
            "low": [99.0] * n + [None]}
    cheap = {k: [x if x is None else (x / 10 if k != "volume" else x) for x in v]
             for k, v in good.items()}
    out = B.preopen_eligible({"A": good, "B": cheap}, n, {})
    assert out == ["A"]                                       # B is under Rs 50


def test_regime_ci_and_summary_render():
    from app.dashboard import lab_data as LD
    from app.lab import summary as SM
    assert LD._ci([1.0, 2.0]) is None
    lo, hi = LD._ci([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    assert 1.0 <= lo <= hi <= 6.0
    rows = [{"strategy": "orb_breadth_core_v1", "enabled": True, "trades": 2, "wins": 1,
             "net_inr": -100, "equity_inr": 990000, "drawdown": 0.06,
             "detail": {"best": "A", "worst": "B"}, "regime_pre": "RANGE",
             "regime_open": "RANGE", "day_type": "UNCLEAR"},
            {"strategy": "bench_c0", "enabled": False, "trades": 0, "wins": 0, "net_inr": 0,
             "equity_inr": 1e6, "drawdown": 0.0, "detail": {}, "regime_pre": None,
             "regime_open": None, "day_type": None}]
    txt = SM.render(_dt.date(2026, 10, 28), rows)
    assert "orb_breadth_core_v1: 2 trades" in txt and "bench_c0: OFF" in txt
    assert "ALERT: orb_breadth_core_v1 drawdown 6.0%" in txt
    assert SM.render(None, []) == ""


def test_p1_compute_records_a_switched_off_variant(monkeypatch):
    from app.shadow import job as SJ
    from app.shadow import spec as SP
    monkeypatch.setattr(SJ.RG, "pre_features", lambda *a, **k: {"nifty_sigma20": 0.01,
                                                                "holiday_thin": False})
    monkeypatch.setattr(SJ.RG, "classify", lambda f: ("RANGE", "r", 0.5))
    monkeypatch.setattr(SJ.RG, "open_features", lambda *a: {"shock_open": False})
    monkeypatch.setattr(SJ.RG, "intraday_features", lambda *a: {})
    monkeypatch.setattr(SJ.RG, "day_type", lambda f: "UNCLEAR")
    monkeypatch.setattr(SJ.RG, "breadth_at", lambda *a: {"breadth_above_open": None})
    monkeypatch.setattr(SJ.BK, "run", lambda c, n, prior_daily_net: ([], [], []))
    monkeypatch.setattr(SJ.BK, "placebo", lambda *a: [])

    class M:
        series: dict = {}  # noqa: RUF012 - a stand-in Market
    off = SP.STRATEGIES[0]
    inp = {"session": _dt.date(2026, 10, 28), "d": 1, "names": {}, "m": M(), "universe": [],
           "idx": {"nifty": {"close": [100.0, None]}}, "results_share": 0.0, "calendar": [],
           "holiday_thin": False, "nifty_1m": [], "excluded_results": [], "excluded_ca": [],
           "fo": [], "fo_info": {}, "switched_off": [off]}
    out = SJ.compute(inp, {})
    sk = [z for z in out["skips"] if z["reason"] == "SWITCHED_OFF"]
    assert [(z["strategy"], z["instrument_key"]) for z in sk] == [(off, "*")]
    assert out["counts"][off] == {"switched_off": True}
    assert all("switched_off" not in out["counts"][x] for x in SP.STRATEGIES[1:])


# ── database ────────────────────────────────────────────────────────────────────────
pytestmark_db = [pytest.mark.db, pytest.mark.integration]
TOKEN = os.environ.get("PRAJNA_WRITE_TOKEN", "test-token-not-a-real-secret")


@pytest.mark.db
@pytest.mark.integration
async def test_switches(db_session):
    from app.core.errors import AuthorizationError
    from app.lab import switches as SW
    cur = await SW.current(db_session)
    assert cur["baseline_gap_fade"]["enabled"] and not cur["baseline_c0"]["enabled"]
    with pytest.raises(AuthorizationError):
        await SW.set_switch(db_session, "bench_c0", False, "test", "wrong")
    with pytest.raises(SW.SwitchRefused):
        await SW.set_switch(db_session, "e5_ensemble", False, "test", TOKEN)
    with pytest.raises(SW.SwitchRefused):
        await SW.set_switch(db_session, "bench_c0", False, "", TOKEN)
    r = await SW.set_switch(db_session, "orb_breadth_core_v1", False, "review", TOKEN)
    assert r["status"] == "CHANGED" and "protocol deviation" in r["warning"]
    assert (await SW.set_switch(db_session, "orb_breadth_core_v1", False, "again", TOKEN)
            )["status"] == "UNCHANGED"
    assert await SW.disabled(db_session, RG.P1) == {"orb_breadth_core_v1"}
    assert await SW.enabled(db_session, RG.PAPER) == ["baseline_gap_fade", "bench_c0"]
    await SW.set_switch(db_session, "orb_breadth_core_v1", True, "back on", TOKEN)
    assert not await SW.disabled(db_session, RG.P1)
    assert len(await SW.history(db_session)) >= 2
    with pytest.raises(Exception, match="append-only"):
        await db_session.execute(text("update strategy_switch set reason = 'x'"))
    await db_session.rollback()


def _out(day: _dt.date, net: float = -250.0) -> dict:
    t = {"strategy": "bench_c0", "family": "PAPER", "source": "paper_fill", "source_id": "1",
         "instrument_key": "NSE_EQ|TEST", "symbol": "TEST", "sector": None, "side": 1,
         "is_placebo": False, "signal_at": T0, "entry_at": T0, "exit_at": T0, "entry_px": 100.0,
         "exit_px": 99.0, "stop": None, "target": None, "qty": 10, "net_inr": net,
         "net_r": None, "exit_reason": "CLOSE", "outcome_class": "CLOSE_LOSS",
         "outcome_rule": "r", "mfe_pct": 0.01, "mae_pct": 0.02, "mfe_r": None, "mae_r": None,
         "target_after_exit": None, "regime_state": None, "day_type": None,
         "ai_verdict": None, "first_news_lag_min": 12.5, "news_before": [{"id": 1}],
         "news_after": [], "plan": {"rank": 1}, "path": {"bars": 3}}
    d = {"strategy": "bench_c0", "family": "PAPER", "enabled": True, "trades": 1, "wins": 0,
         "losses": 1, "gross_inr": -230.0, "charges_inr": 20.0, "net_inr": net, "net_r": None,
         "placebo_trades": None, "placebo_net_inr": None, "regime_pre": None,
         "regime_open": None, "day_type": None, "equity_inr": 1e6 + net, "drawdown": 0.0003,
         "detail": {"classes": {"CLOSE_LOSS": 1}}}
    f = {"strategy": "bench_c0", "thought": {"x": 1}, "happened": {"y": 2},
         "why": [{"code": "RESULT", "en": "e", "hi": "h"}]}
    return {"session": day, "trades": [t], "days": [d], "forensics": [f],
            "inputs_sha256": f"{abs(hash((day, net))):064d}"[-64:], "counts": {"PAPER": 1}}


@pytest.mark.db
@pytest.mark.integration
async def test_store_versions_runs_and_is_append_only(db_session):
    from app.core.errors import AuthorizationError
    from app.lab import store as ST
    day = _dt.date(2026, 10, 28)
    with pytest.raises(AuthorizationError):
        await ST.record_daily(db_session, _out(day), token=None, code_git_sha="t")
    r1 = await ST.record_daily(db_session, _out(day), token=TOKEN, code_git_sha="t")
    assert r1["status"] == "WRITTEN"
    assert (await ST.record_daily(db_session, _out(day), token=TOKEN, code_git_sha="t")
            )["status"] == "UNCHANGED"
    r3 = await ST.record_daily(db_session, _out(day, -400.0), token=TOKEN, code_git_sha="t")
    assert r3["status"] == "WRITTEN" and r3["run_id"] != r1["run_id"]
    from app.dashboard import lab_data as LD
    d = await LD.day(db_session, day)
    assert d["available"] and d["strategies"][0]["net_inr"] == pytest.approx(-400.0)
    assert d["trades"][0]["n_before"] == 1
    assert d["forensics"]["bench_c0"]["why"][0]["code"] == "RESULT"
    hist = await LD.history(db_session, "bench_c0")
    assert [h["net_inr"] for h in hist if h["session_date"] == day] == [pytest.approx(-400.0)]
    ov = await LD.overview(db_session)
    b = next(x for x in ov["strategies"] if x["strategy"] == "bench_c0")
    assert b["trades"] >= 1 and b["switchable"]
    rg = await LD.regime(db_session, day, day)
    assert any(c["strategy"] == "bench_c0" and c["too_few"] for c in rg["cells"])
    with pytest.raises(Exception, match="append-only"):
        await db_session.execute(text("delete from trade_forensic"))
    await db_session.rollback()


@pytest.mark.db
@pytest.mark.integration
async def test_dashboard_switch_needs_the_token(monkeypatch):
    import httpx
    monkeypatch.setenv("PRAJNA_DASHBOARD_LIVE", "0")
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)   # FastAPI on_event (existing)
        from app.dashboard import server as SV
    transport = httpx.ASGITransport(app=SV.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/lab/switch", json={"strategy": "bench_c0", "on": False,
                                                  "reason": "test"},
                         headers={"X-Prajna-Token": "wrong"})
        assert r.status_code == 403
        r = await c.post("/api/lab/switch", json={"strategy": "bench_c0", "on": False,
                                                  "reason": "test"})
        assert r.status_code == 403
