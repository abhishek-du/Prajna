"""Upstox calendar -> trading_session: provenance, idempotence, no overwrite."""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os

import pytest
from sqlalchemy import text

from app.ingest.calendar import ingest_calendar
from app.storage.payload_store import PayloadStore
from tests.support.upstox_calendar import EMPTY, HOLIDAYS, FakeCalendar, holidays_with

pytestmark = [pytest.mark.db, pytest.mark.integration]
TOKEN = os.environ["PRAJNA_WRITE_TOKEN"]
D = _dt.date


async def _ingest(s, tmp_path, cal, *, frm=D(2026, 9, 24), to=D(2026, 10, 4), commit=True):
    return await ingest_calendar(s, date_from=frm, date_to=to, holidays=cal.holidays,
                                 timings=cal.timings, store=PayloadStore(tmp_path),
                                 commit=commit, token=TOKEN if commit else None)


async def _rows(s):
    return {r.session_date: r for r in (await s.execute(text(
        "select * from trading_session order by session_date"))).all()}


async def test_a_real_fortnight_is_classified_and_persisted(db_session, tmp_path):
    rep = await _ingest(db_session, tmp_path, FakeCalendar())
    assert rep.status == "COMPLETE", rep.anomalies
    rows = await _rows(db_session)
    assert len(rows) == 11
    assert rows[D(2026, 9, 24)].session_type == "NORMAL"
    assert rows[D(2026, 9, 26)].session_type == "WEEKEND"
    assert rows[D(2026, 10, 2)].session_type == "HOLIDAY" and not rows[D(2026, 10, 2)].open_ist
    assert rep.by_type == {"NORMAL": 6, "WEEKEND": 4, "HOLIDAY": 1}


async def test_every_row_points_at_its_archived_payloads(db_session, tmp_path):
    cal = FakeCalendar()
    rep = await _ingest(db_session, tmp_path, cal)
    r = (await db_session.execute(text("""
        select t.payload_sha256, t.note, t.knowable_at, t.fetched_at, t.knowable_at_verified,
               p.vendor_endpoint, p.storage_uri
        from trading_session t join raw_payload p using (payload_sha256)
        where t.session_date = '2026-09-24'"""))).one()
    note = json.loads(r.note)
    assert note["holidays_payload_sha256"] == hashlib.sha256(HOLIDAYS).hexdigest()
    assert note["holidays_payload_sha256"] == rep.holidays_sha256
    assert r.vendor_endpoint.endswith("/v2/market/timings/2026-09-24")
    assert PayloadStore.read(r.storage_uri, r.payload_sha256)
    assert r.knowable_at == r.fetched_at and r.knowable_at_verified is False
    assert cal.calls[0] == "holidays" and len(cal.calls) == 1 + 11   # one timings per day


async def test_repeated_run_is_a_no_op(db_session, tmp_path):
    await _ingest(db_session, tmp_path, FakeCalendar())
    again = await _ingest(db_session, tmp_path, FakeCalendar())
    assert again.status == "COMPLETE" and again.rows_written == 0
    assert again.already_recorded == 11


async def test_a_changed_calendar_is_refused_not_overwritten(db_session, tmp_path):
    await _ingest(db_session, tmp_path, FakeCalendar())
    new_holiday = {"date": "2026-09-25", "description": "Surprise", "holiday_type":
                   "TRADING_HOLIDAY", "closed_exchanges": ["NSE"], "open_exchanges": []}
    rep = await _ingest(db_session, tmp_path, FakeCalendar(holidays_with(extra=[new_holiday])))
    assert rep.status == "FAILED"
    dup = next(a for a in rep.anomalies if a["kind"] == "DUPLICATE_KEY")
    assert dup["subject"] == "trading_session[2026-09-25]"
    assert (await _rows(db_session))[D(2026, 9, 25)].session_type == "NORMAL"


async def test_one_contradiction_fails_the_whole_run(db_session, tmp_path):
    """A weekday that is neither open nor a listed holiday: nothing is written,
    not even the days that were fine."""
    cal = FakeCalendar(holidays_with(drop={"2026-10-02"}), overrides={D(2026, 10, 2): EMPTY})
    rep = await _ingest(db_session, tmp_path, cal)
    assert rep.status == "FAILED" and await _rows(db_session) == {}
    assert any("weekday with no NSE timings" in (a["detail"].get("reason") or "")
               for a in rep.anomalies)


async def test_dry_run_archives_but_writes_no_sessions(db_session, tmp_path):
    rep = await _ingest(db_session, tmp_path, FakeCalendar(), commit=False)
    assert rep.status == "COMPLETE" and rep.rows_written == 0
    assert await _rows(db_session) == {}
    assert list(tmp_path.rglob("*.json.gz"))


async def test_special_sessions_carry_vendor_hours(db_session, tmp_path):
    rep = await _ingest(db_session, tmp_path, FakeCalendar(), frm=D(2026, 11, 7),
                        to=D(2026, 11, 10))
    assert rep.status == "COMPLETE", rep.anomalies
    rows = await _rows(db_session)
    m = rows[D(2026, 11, 8)]
    assert (m.session_type, m.open_ist, m.close_ist) == ("SPECIAL", _dt.time(18),
                                                         _dt.time(19))
    assert m.preopen_start_ist is None
    assert rows[D(2026, 11, 10)].session_type == "HOLIDAY"
    assert rows[D(2026, 11, 9)].session_type == "NORMAL"
