"""The single look (`models report --look`) end to end on synthetic forward sessions in the
test database: it waits for 40 sessions and for their outcomes, computes A1-A4, records
the look and refuses a second; a session without usable values is reported, not dropped.
Synthetic panels only (never production data, so this is no look at E5)."""

from __future__ import annotations

import datetime as _dt

import numpy as np
import pytest

pytest.importorskip("lightgbm")
pytest.importorskip("torch")

from app.core.clock import now
from app.models import data as D
from app.models import forward as F
from app.models import recipe as R
from tests.models.test_e5 import panel
from tests.models.test_e5_insert import _model

pytestmark = [pytest.mark.db, pytest.mark.integration]
SHA = "e" * 64                         # the model_version row of test_e5_insert._model


@pytest.fixture(scope="module")
def world():
    p = panel(R.TRAIN_SESSIONS + F.FORWARD_SESSIONS, signal=0.04, seed=7)
    b = R.fit(p, list(range(R.TRAIN_SESSIONS)))
    return p, b


async def _forward(s, p, b, n=F.FORWARD_SESSIONS):
    await _model(s)
    at = now()
    for t in range(R.TRAIN_SESSIONS, R.TRAIN_SESSIONS + n):
        out = R.predict(b, p, t)
        picks = set(R.select(out, b.cost, results_today=set()))
        order = sorted(range(len(out["keys"])), key=lambda j: (-out["score"][j], out["keys"][j]))
        rank = {j: i + 1 for i, j in enumerate(order)}
        rows = [{"m": SHA, "d": p[t].date, "sn": "PRE_SESSION", "k": out["keys"][j],
                 "p": float(out["prob_up"][j]), "e": float(out["exp_return"][j]),
                 "lo": float(out["range_lo"][j]), "hi": float(out["range_hi"][j]),
                 "v": float(out["volatility"][j]), "c": float(out["confidence"][j]),
                 "sc": float(out["score"][j]), "r": rank[j], "sel": j in picks,
                 "fa": at - _dt.timedelta(minutes=5), "ih": "b" * 64, "pa": at,
                 "dl": at + _dt.timedelta(hours=1)} for j in range(len(out["keys"]))]
        await F.insert_predictions(s, rows)
    await s.commit()


@pytest.fixture
def wired(monkeypatch, tmp_path, world):
    """load_model, live_session, outcomes and readiness from the synthetic panel."""
    p, b = world
    by_date = {x.date: x for x in p}
    state = {"drop": set(), "no_bars": set()}

    async def load_model(s, sha=None):
        return SHA, b

    async def live_session(s, d):
        if d in state["drop"]:
            return None
        x = by_date[d]
        return D.Session(d, x.keys, x.X, {lb: np.full(len(x.keys), np.nan) for lb in D.LABELS},
                         np.zeros(len(x.keys), dtype=bool), "feature_value")

    async def outcomes(s, d, keys):
        x = by_date[d]
        pos = {k: i for i, k in enumerate(x.keys)}
        o = 100.0
        return {k: (o, o * (1 + x.y["high_exc"][pos[k]]), o * (1 + x.y["low_exc"][pos[k]]),
                    o * (1 + x.y["ret_oc"][pos[k]])) for k in keys}

    async def outcome_readiness(s, sha):
        from sqlalchemy import text
        days = (await s.execute(text("""select session_date, count(*) from model_prediction
            where model_sha256 = :m group by 1 order by 1"""), {"m": sha})).all()
        return [{"session": str(d), "predicted": n, "with_bar": 0 if d in state["no_bars"]
                 else n, "ready": d not in state["no_bars"]} for d, n in days]

    monkeypatch.setattr(F, "load_model", load_model)
    monkeypatch.setattr(D, "live_session", live_session)
    monkeypatch.setattr(F, "outcomes", outcomes)
    monkeypatch.setattr(F, "outcome_readiness", outcome_readiness)
    monkeypatch.setattr(F, "LEDGER", tmp_path / "e5" / "forward_ledger.jsonl")
    return p, b, state


async def test_waits_for_forty_sessions(db_session, wired):
    p, b, _ = wired
    await _forward(db_session, p, b, n=39)
    with pytest.raises(F.Refused, match="39 of 40"):
        await F.report(db_session, look=True)


async def test_waits_for_outcomes_then_looks_once(db_session, wired):
    p, b, state = wired
    await _forward(db_session, p, b)
    state["no_bars"] = {p[-1].date}
    with pytest.raises(F.Refused, match="outcomes not ready for 1 session"):
        await F.report(db_session, look=True)
    state["no_bars"] = set()
    with pytest.raises(F.Refused, match="needs --look"):
        await F.report(db_session)
    state["drop"] = {p[R.TRAIN_SESSIONS + 3].date}
    rep = await F.report(db_session, look=True)
    assert set(rep["gates"]) == {"A1_ci_above_zero", "A2_stress_mean_ge_zero",
                                 "A3_both_halves_positive", "A4_placebo_ci_contains_zero"}
    assert rep["verdict"] in ("ACCEPTED", "NOT_ACCEPTED")
    assert rep["verdict"] == ("ACCEPTED" if all(rep["gates"].values()) else "NOT_ACCEPTED")
    assert len(rep["per_session"]) == F.FORWARD_SESSIONS - 1
    assert rep["not_evaluable_sessions"] == [
        {"session": str(p[R.TRAIN_SESSIONS + 3].date), "reason": "no usable PRE_SESSION values"}]
    assert (F.LEDGER.parent / f"forward_look_{SHA[:12]}.json").exists()
    with pytest.raises(F.Refused, match="already had its look"):
        await F.report(db_session, look=True)


async def test_planted_signal_passes_a1(db_session, wired):
    """A strong planted reversal (4 % spread) is detected: A1 holds."""
    p, b, _ = wired
    await _forward(db_session, p, b)
    rep = await F.report(db_session, look=True)
    assert rep["gates"]["A1_ci_above_zero"], rep["pooled"]
