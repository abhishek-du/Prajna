"""model_prediction inserts report the rows really added (2026-10-22: asyncpg's
executemany rowcount is -1, logged as inserted=-1)."""

from __future__ import annotations

import datetime as _dt

import pytest
from sqlalchemy import text

from app.core.clock import now
from app.models.forward import insert_predictions

pytestmark = [pytest.mark.db, pytest.mark.integration]
SHA = "e" * 64
DAY = _dt.date(2026, 10, 23)


async def _model(s):
    await s.execute(text("""insert into model_version (model_sha256, recipe, purpose,
        trained_from, trained_to, train_sessions, train_rows, artefact_path, artefact_sha256,
        code_git_sha, config, created_at, authz_token_sha256) values (:m, 'e5-recipe-v2',
        'RESEARCH', '2026-01-01', '2026-02-01', 20, 100, 'x', :a, 'g', '{}', :n, :a)"""),
        {"m": SHA, "a": "a" * 64, "n": now()})


def _rows(keys):
    at = now()
    return [{"m": SHA, "d": DAY, "sn": "PRE_SESSION", "k": k, "p": 0.5, "e": 0.0, "lo": -0.01,
             "hi": 0.01, "v": 0.02, "c": 0.5, "sc": 0.5, "r": i + 1, "sel": False,
             "fa": at - _dt.timedelta(minutes=5), "ih": "b" * 64, "pa": at,
             "dl": at + _dt.timedelta(hours=1)} for i, k in enumerate(keys)]


async def test_inserted_counts_new_rows_and_a_rerun_adds_none(db_session):
    await _model(db_session)
    assert await insert_predictions(db_session, _rows(["NSE_EQ|A", "NSE_EQ|B", "NSE_EQ|C"])) == 3
    assert await insert_predictions(db_session, _rows(["NSE_EQ|A", "NSE_EQ|B", "NSE_EQ|D"])) == 1
    assert await insert_predictions(db_session, []) == 0
