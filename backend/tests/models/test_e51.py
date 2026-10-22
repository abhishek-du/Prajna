"""E5.1 refits (docs/STAGE4_E5_AFTER_THE_LOOK.md §4): inactive until E5 is ACCEPTED, the
refusal rules, lineage (previous_sha256, DB CHECK), one model per session and the swap
from the next session. Synthetic panels in the test database; artefacts in tmp."""

from __future__ import annotations

import datetime as _dt
import json

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

pytest.importorskip("lightgbm")
pytest.importorskip("torch")

from app.core.clock import IST, now
from app.models import data as D
from app.models import forward as F
from app.models import recipe as R
from tests.models.test_e5 import panel

pytestmark = [pytest.mark.db, pytest.mark.integration]
BASE = "f" * 64
N = R.TRAIN_SESSIONS + D.SEQ_LEN + F.REFIT_EVERY


@pytest.fixture(scope="module")
def world():
    return panel(N, signal=0.04, seed=11)


async def _base(s, trained_to):
    await s.execute(text("""insert into model_version (model_sha256, recipe, purpose,
        trained_from, trained_to, train_sessions, train_rows, artefact_path, artefact_sha256,
        code_git_sha, config, created_at, authz_token_sha256) values (:m, 'e5-recipe-v2',
        'FORWARD_TEST', '2025-01-01', :t, 120, 100, 'x', :a, 'g', '{}', :n, :a)"""),
        {"m": BASE, "t": trained_to, "a": "a" * 64,
         "n": now() - _dt.timedelta(days=60)})
    await s.commit()


@pytest.fixture
def wired(monkeypatch, tmp_path, world):
    by = {x.date: x for x in world}

    async def training_sessions(s, dataset=D.TRAIN_DATASET):
        assert dataset == F.E51_DATASET
        return sorted(by)

    async def training_session(s, d, dataset=D.TRAIN_DATASET):
        return by[d]

    monkeypatch.setattr(D, "training_sessions", training_sessions)
    monkeypatch.setattr(D, "training_session", training_session)
    monkeypatch.setattr(F, "LEDGER", tmp_path / "ledger.jsonl")
    monkeypatch.setattr(F, "ART", tmp_path / "models")
    monkeypatch.setattr(F, "ROOT", tmp_path)
    monkeypatch.setattr(F, "MIN_UNIVERSE", 100)
    import app.training.replay as RP
    monkeypatch.setattr(RP, "code_version", lambda: {"git_sha": "t" * 40, "dirty": False})
    return world


def _accept(verdict="ACCEPTED"):
    F.LEDGER.write_text(json.dumps({"phase": "look", "model_sha256": BASE,
                                    "verdict": verdict}) + "\n")


TOKEN = __import__("os").environ["PRAJNA_WRITE_TOKEN"]


async def test_inactive_until_accepted(db_session, wired):
    await _base(db_session, wired[R.TRAIN_SESSIONS].date)
    with pytest.raises(F.Refused, match="not ACCEPTED"):
        await F.refit(db_session)
    _accept("NOT_ACCEPTED")
    with pytest.raises(F.Refused, match="not ACCEPTED"):
        await F.production_model_for(db_session, now().date())


async def test_cadence(db_session, wired):
    await _base(db_session, wired[-F.REFIT_EVERY].date)    # only 19 newer labelled sessions
    _accept()
    with pytest.raises(F.Refused, match="a refit every 20"):
        await F.refit(db_session)


async def test_refit_lineage_and_refusals(db_session, wired, monkeypatch):
    p = wired
    await _base(db_session, p[-F.REFIT_EVERY - 1].date)
    _accept()
    monkeypatch.setattr(F, "MIN_UNIVERSE", 10_000)
    with pytest.raises(F.Refused, match="universe"):
        await F.refit(db_session)
    monkeypatch.setattr(F, "MIN_UNIVERSE", 100)

    out = await F.refit(db_session, commit=True, token=TOKEN)
    assert out["previous"] == BASE and out["new_sessions"] == F.REFIT_EVERY
    row = (await db_session.execute(text("""select purpose, previous_sha256, trained_to
        from model_version where model_sha256 = :m"""), {"m": out["model_sha256"]})).one()
    assert row.purpose == "PRODUCTION" and row.previous_sha256 == BASE
    assert row.trained_to == p[-1].date
    assert (F.ART / out["model_sha256"] / "bundle.pkl").exists()
    with pytest.raises(F.Refused, match="0 labelled sessions after"):   # cadence
        await F.refit(db_session)

    today = now().astimezone(IST).date()
    assert await F.production_model_for(db_session, today) == BASE      # effective tomorrow
    tomorrow = today + _dt.timedelta(days=1)
    assert await F.production_model_for(db_session, tomorrow) == out["model_sha256"]
    await db_session.execute(text("""insert into model_prediction (model_sha256, session_date,
        snapshot, instrument_key, prob_up, exp_return, range_lo, range_hi, volatility,
        confidence, score, rank, selected, features_as_of, inputs_sha256, predicted_at,
        deadline_at) values (:m, :d, 'PRE_SESSION', 'NSE_EQ|X', .5, 0, -.01, .01, .02, .5,
        .5, 1, false, :a, :h, :a, :dl)"""),
        {"m": BASE, "d": tomorrow, "a": now(), "h": "b" * 64,
         "dl": now() + _dt.timedelta(hours=1)})
    with pytest.raises(F.Refused, match="one model per session"):
        await F.production_model_for(db_session, tomorrow)


async def test_production_needs_a_predecessor(db_session):
    with pytest.raises(IntegrityError, match="ck_model_version_lineage"):
        await db_session.execute(text("""insert into model_version (model_sha256, recipe,
            purpose, trained_from, trained_to, train_sessions, train_rows, artefact_path,
            artefact_sha256, code_git_sha, config, created_at, authz_token_sha256) values
            (:m, 'r', 'PRODUCTION', '2025-01-01', '2025-02-01', 1, 1, 'x', :a, 'g', '{}',
            :n, :a)"""), {"m": "9" * 64, "a": "a" * 64, "n": now()})
