"""app/shadow/review.py: the answer schema, the outcome-blind PIT packet, the freeze,
the failsafe (failures count as PASS), idempotent pending and the database rules.
A fake model: no network."""

from __future__ import annotations

import datetime as _dt
import json
import os

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.shadow import review as RV
from app.shadow import spec as SP
from app.shadow import store as SS
from app.shadow.bars import at
from tests.shadow.test_store import DAY, FWD, INP, _out
from tests.stage3.test_features_v5 import _item, _poll

TOKEN = os.environ["PRAJNA_WRITE_TOKEN"]
KEY = "NSE_EQ|INE000000001"
SIG = at(DAY, "10:00")
PK = {"evidence": [{"id": "news:1"}, {"id": "regime:PRE"}]}


# ── schema ────────────────────────────────────────────────────────────────────────
def _a(**kw):
    d = {"verdict": "PASS", "reason_codes": [], "evidence_ids": [], "note": ""} | kw
    return json.dumps(d)


@pytest.mark.parametrize("answer,status,eff", [
    (_a(), "OK", "PASS"),
    (_a(verdict="veto", reason_codes=["unseen_material_news"], evidence_ids=["news:1"]),
     "OK", "VETO"),
    ("```json\n" + _a(verdict="SHRINK", reason_codes=["MACRO_EVENT_WINDOW"],
                      evidence_ids=["regime:PRE"]) + "\n```", "OK", "SHRINK"),
    (_a(verdict="VETO", reason_codes=["UNSEEN_MATERIAL_NEWS"], evidence_ids=["news:99"]),
     "INVALID_EVIDENCE", "PASS"),                   # a cited id that is not in the packet
    (_a(verdict="VETO", reason_codes=["UNSEEN_MATERIAL_NEWS"]), "INVALID_EVIDENCE", "PASS"),
    (_a(verdict="VETO", reason_codes=["BUY_MORE"], evidence_ids=["news:1"]), "INVALID", "PASS"),
    (_a(verdict="BUY"), "INVALID", "PASS"),
    (_a(verdict="VETO", reason_codes=["OTHER"], evidence_ids=["news:1"], note=" "),
     "INVALID", "PASS"),
    ('{"verdict": "PASS"}', "INVALID", "PASS"),
    ("no json here", "INVALID", "PASS"),
])
def test_answer_schema_and_failsafe(answer, status, eff):
    st, d, _ = RV.validate(answer, PK)
    assert st == status and RV.effective(st, d) == eff


def test_spec_is_pinned():
    sp = RV.spec()
    assert sp["model_id"] == RV.MODEL_ID and sp["temperature"] == 0
    assert len(RV.spec_sha256()) == 64 and sp["failsafe"] == "PASS"


# ── database ──────────────────────────────────────────────────────────────────────
@pytest.fixture
def frozen(monkeypatch):
    monkeypatch.setattr(SP, "FORWARD_FROM", FWD)
    monkeypatch.setattr(RV, "FORWARD_FROM", FWD)


async def _world(s):
    await SS.freeze(s, forward_from=FWD, token=TOKEN, code_git_sha="abc")
    out = _out()
    out["trades"][0]["signal_at"] = SIG
    await SS.record(s, DAY, INP, out, cutoff=at(DAY, "21:30"), token=TOKEN, code_git_sha="abc")
    pid = await _poll(s, "NSE_ANNOUNCEMENTS", t=SIG - _dt.timedelta(days=1))
    before = await _item(s, pid, source="NSE_ANNOUNCEMENTS", title="Board approves buyback",
                         knowable=SIG - _dt.timedelta(hours=3), links=((KEY, 0.9, None),))
    after = await _item(s, pid, source="NSE_ANNOUNCEMENTS", title="Results announced",
                        knowable=SIG + _dt.timedelta(minutes=5), links=((KEY, 0.9, None),))
    late_link = await _item(s, pid, source="NSE_ANNOUNCEMENTS", title="Order win",
                            knowable=SIG - _dt.timedelta(hours=1),
                            links=((KEY, 0.9, SIG + _dt.timedelta(minutes=1)),))
    old = await _item(s, pid, source="NSE_ANNOUNCEMENTS", title="Old item",
                      knowable=SIG - _dt.timedelta(hours=60), links=((KEY, 0.9, None),))
    return before, after, late_link, old


async def _trade(s):
    return (await s.execute(text("select * from shadow_trade"))).first()


def _fake(answer):
    calls = []

    async def model(model_id, prompt):
        calls.append(prompt)
        return answer(prompt) if callable(answer) else answer, "v1"
    return model, calls


async def test_packet_is_point_in_time_and_blind(db_session, frozen):
    s = db_session
    before, after, late_link, old = await _world(s)
    p = await RV.packet(s, await _trade(s))
    ids = {e["id"] for e in p["evidence"]}
    assert f"news:{before}" in ids
    assert f"news:{after}" not in ids              # knowable after the signal
    assert f"news:{late_link}" not in ids          # linked to the stock after the signal
    assert f"news:{old}" not in ids                # outside the 48 h window
    body = json.dumps(p, default=str)
    for k in RV.OUTCOME_KEYS:
        assert f'"{k}"' not in body
    assert p["trade"]["side"] == "LONG" and p["base"] == SP.S2


async def test_run_needs_the_freeze_then_records_once(db_session, frozen):
    s = db_session
    before, *_ = await _world(s)
    model, calls = _fake(lambda pr: _a(verdict="VETO", reason_codes=["UNSEEN_MATERIAL_NEWS"],
                                       evidence_ids=[f"news:{before}"], note="buyback"))
    with pytest.raises(RV.ReviewRefused, match="not frozen"):
        await RV.run(s, model, commit=True, token=TOKEN, code_git_sha="abc")
    r = await RV.freeze(s, forward_from=FWD, token=TOKEN, code_git_sha="abc")
    assert r["status"] == "WRITTEN"
    res = await RV.run(s, model, commit=True, token=TOKEN, code_git_sha="abc")
    assert res["reviewed"] == 1 and res["mix"] == {"OK:VETO": 1} and len(calls) == 1
    row = (await s.execute(text("select * from llm_review"))).first()
    assert row.effective_verdict == "VETO" and row.evidence_ids == [f"news:{before}"]
    assert row.prompt_sha256 and row.packet_sha256 and row.mode == "SHADOW"
    again = await RV.run(s, model, commit=True, token=TOKEN, code_git_sha="abc")
    assert again["reviewed"] == 0 and len(calls) == 1          # nothing pending


async def test_failures_count_as_pass_and_rows_are_append_only(db_session, frozen):
    s = db_session
    await _world(s)
    await RV.freeze(s, forward_from=FWD, token=TOKEN, code_git_sha="abc")

    async def broken(model_id, prompt):
        raise RuntimeError("throttled")
    res = await RV.run(s, broken, commit=True, token=TOKEN, code_git_sha="abc")
    assert res["mix"] == {"ERROR:PASS": 1}
    row = (await s.execute(text("select status, effective_verdict, response_raw from llm_review"))).first()
    assert tuple(row) == ("ERROR", "PASS", None)
    for sql in ("update llm_review set effective_verdict = 'VETO'", "delete from llm_review",
                "update llm_reviewer set model_id = 'x'"):
        with pytest.raises(DBAPIError, match="append-only"):
            async with s.begin_nested():
                await s.execute(text(sql))
    tid = (await s.execute(text("select id from shadow_trade"))).scalar()
    with pytest.raises(DBAPIError, match="ck_llm_review_failsafe"):
        async with s.begin_nested():
            await s.execute(text("""insert into llm_review (trade_id, reviewer_version,
                policy_version, market_date, strategy, instrument_key, is_placebo, model_id,
                prompt_version, prompt_sha256, packet, packet_sha256, n_evidence, status,
                reason_codes, evidence_ids, effective_verdict, code_git_sha,
                authz_token_sha256, created_at, mode) values (:t, :v, :p, :d, 's', 'k', true,
                'm', 'pv', :h, '{}', :h, 0, 'INVALID', '{}', '{}', 'VETO', 'g', :h, now(),
                'SHADOW')"""), {"t": tid, "v": RV.REVIEWER_VERSION, "p": SP.POLICY_VERSION,
                                "d": DAY, "h": "a" * 64})


async def test_dry_run_writes_nothing(db_session, frozen):
    s = db_session
    await _world(s)
    model, calls = _fake(_a())
    res = await RV.run(s, model, commit=False, token=None, code_git_sha="abc")
    assert res["reviewed"] == 1 and res["commit"] is False and len(calls) == 1
    assert (await s.execute(text("select count(*) from llm_review"))).scalar() == 0
