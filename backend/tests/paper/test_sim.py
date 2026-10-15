"""app/paper/sim.py: the paper MIS simulator (Stage 7 step 1). Pure; and the paper-only
safety rule (design P9): the package cannot reach a broker or the network."""

from __future__ import annotations

import ast
import math
import pathlib

import pytest

from app.paper import sim as S
from app.training import e2 as X

PAPER = pathlib.Path(__file__).resolve().parents[2] / "app" / "paper"
CFG = S.Config()
BAR = S.Bar(open=100.0, high=104.0, low=99.0, close=102.0, prev_volume=1_000_000)


def test_a_hand_computed_fill():
    f = S.fill_one("A", BAR, CFG)
    buy, sell = 100.0 * 1.0005, 102.0 * 0.9995
    qty = math.floor(100_000 / buy)
    assert (f.status, f.qty) == ("FILLED", qty) and f.qty == 999
    assert f.buy_px == pytest.approx(buy) and f.sell_px == pytest.approx(sell)
    b, s = X.order_cost_parts(qty * buy, "BUY", CFG.rates), \
        X.order_cost_parts(qty * sell, "SELL", CFG.rates)
    assert f.charges == pytest.approx({p: b[p] + s[p] for p in b})
    assert f.pnl_inr == pytest.approx(qty * (sell - buy) - sum(f.charges.values()))
    assert f.mode == "PAPER"


@pytest.mark.parametrize(("bar", "reason"), [
    (None, "no_open_or_close"),
    (S.Bar(None, 104, 99, 102, 1e6), "no_open_or_close"),
    (S.Bar(100, 104, 99, float("nan"), 1e6), "no_open_or_close"),
    (S.Bar(100, 100, 100, 100, 1e6), "locked_day"),
    (S.Bar(100, 104, 99, 102, None), "participation_cap"),
    (S.Bar(200_000, 200_100, 199_900, 200_050, 1e6), "zero_quantity"),
])
def test_no_fill_rules(bar, reason):
    f = S.fill_one("A", bar, CFG)
    assert (f.status, f.reason, f.qty, f.pnl_inr) == ("NOT_FILLED", reason, 0, 0.0)


def test_the_participation_cap_gives_a_partial_fill():
    f = S.fill_one("A", S.Bar(100, 104, 99, 102, 50_000), CFG)      # 1% = 500 shares
    assert (f.status, f.qty, f.reason) == ("PARTIAL", 500, "participation_cap")


def test_the_session_pnl_identity_and_cash_limit():
    bars = {k: BAR for k in "ABCDEFGHIJKL"}
    r = S.simulate(list("ABCDEFGHIJKL"), bars, CFG)
    assert r["filled"] == 10 and r["not_filled"] == {"insufficient_cash": 2}  # 10 x 99,950
    fills = [f for f in r["fills"] if f["qty"]]
    gross = sum(f["sell_value"] - f["buy_value"] for f in fills)
    assert r["end_cash"] - r["start_cash"] == pytest.approx(gross - r["charges_inr"])
    assert r["pnl_inr"] == pytest.approx(sum(f["pnl_inr"] for f in fills))
    assert r["mode"] == "PAPER"


def test_deterministic_and_duplicates_refused():
    bars = {"A": BAR, "B": S.Bar(50, 51, 49, 49.5, 1e6)}
    assert S.simulate(["A", "B"], bars) == S.simulate(["A", "B"], bars)
    assert S.simulate(["A", "B"], bars)["sha256"] != S.simulate(["B", "A"], bars)["sha256"]
    with pytest.raises(ValueError, match="duplicate"):
        S.simulate(["A", "A"], bars)


def test_paper_package_cannot_reach_a_broker_or_the_network():
    banned = ("app.vendor", "httpx", "requests", "websockets", "aiohttp", "urllib", "socket",
              "app.connectors", "app.sources")
    for py in PAPER.rglob("*.py"):
        tree = ast.parse(py.read_text())
        for node in ast.walk(tree):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import) else
                     [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            for n in names:
                assert not any(n == b or n.startswith(b + ".") for b in banned), (py, n)
        assert "place_order" not in py.read_text() and "/order/" not in py.read_text()
