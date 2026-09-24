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


class _PastCalendar(FakeCalendar):
    """A 2024 week: real shifted timings on trading days, empty on the holiday
    and the weekend; the per-date holiday answers are the REAL recorded ones."""

    def __init__(self, closed_days, per_date):
        super().__init__()
        self.past_closed = set(closed_days)
        self.per_date = per_date

    async def timings(self, day):
        from app.core.clock import now
        from app.sources.upstox_calendar import API, TIMINGS_PATH, Fetched
        from tests.support.upstox_calendar import timings_for
        data = EMPTY if (day in self.past_closed or day.weekday() >= 5) else timings_for(day)
        return Fetched(API + TIMINGS_PATH.format(date=day), data, now(), 200)

    async def holiday_on(self, day):
        from app.core.clock import now
        from app.sources.upstox_calendar import API, HOLIDAYS_PATH, Fetched
        from tests.support.upstox_calendar import real
        self.calls.append(f"holiday_on:{day}")
        return Fetched(f"{API}{HOLIDAYS_PATH}/{day}", real(self.per_date[day]), now(), 200)


async def test_past_holiday_is_decided_from_the_per_date_answer(db_session, tmp_path):
    cal = _PastCalendar({D(2024, 1, 26)}, {D(2024, 1, 26): "holidays_on_2024-01-26.json"})
    rep = await ingest_calendar(db_session, date_from=D(2024, 1, 25), date_to=D(2024, 1, 29),
                                holidays=cal.holidays, timings=cal.timings,
                                store=PayloadStore(tmp_path), commit=True, token=TOKEN,
                                holiday_on=cal.holiday_on)
    assert rep.status == "COMPLETE", rep.anomalies
    rows = await _rows(db_session)
    assert rows[D(2024, 1, 26)].session_type == "HOLIDAY"
    assert [rows[D(2024, 1, d)].session_type for d in (25, 27, 28, 29)] == \
        ["NORMAL", "WEEKEND", "WEEKEND", "NORMAL"]
    assert cal.calls.count("holiday_on:2024-01-26") == 1          # asked only where needed
    assert not [c for c in cal.calls if c.startswith("holiday_on:") and "26" not in c]


async def test_past_weekday_without_timings_or_holiday_is_refused(db_session, tmp_path):
    cal = _PastCalendar({D(2024, 1, 25)}, {D(2024, 1, 25): "holidays_on_ordinary_day.json"})
    rep = await ingest_calendar(db_session, date_from=D(2024, 1, 25), date_to=D(2024, 1, 25),
                                holidays=cal.holidays, timings=cal.timings,
                                store=PayloadStore(tmp_path), commit=True, token=TOKEN,
                                holiday_on=cal.holiday_on)
    assert rep.status == "FAILED"                  # never guessed as a holiday
    assert not await _rows(db_session)


class _GenericPast(_PastCalendar):
    """Past dates as Upstox really answers them (measured 2026-09-24): the
    timings endpoint gives the generic open schedule on EVERY weekday,
    holidays included."""

    async def timings(self, day):
        from app.core.clock import now
        from app.sources.upstox_calendar import API, TIMINGS_PATH, Fetched
        from tests.support.upstox_calendar import timings_for
        data = EMPTY if day.weekday() >= 5 else timings_for(day)
        return Fetched(API + TIMINGS_PATH.format(date=day), data, now(), 200)


async def _past(s, tmp_path, cal, bars, frm, to):
    return await ingest_calendar(s, date_from=frm, date_to=to, holidays=cal.holidays,
                                 timings=cal.timings, store=PayloadStore(tmp_path),
                                 commit=True, token=TOKEN, holiday_on=cal.holiday_on,
                                 past_before=D(2026, 9, 24), index_bar_dates=bars)


async def test_past_holiday_with_generic_open_timings_is_a_holiday(db_session, tmp_path):
    """The 2020-2022 defect: timings said open on Republic Day. With the index
    bars as evidence the holiday is a HOLIDAY."""
    cal = _GenericPast(set(), {D(2024, 1, 26): "holidays_on_2024-01-26.json"})
    bars = {D(2024, 1, 25), D(2024, 1, 29)}
    rep = await _past(db_session, tmp_path, cal, bars, D(2024, 1, 25), D(2024, 1, 29))
    assert rep.status == "COMPLETE", rep.anomalies
    rows = await _rows(db_session)
    assert [rows[D(2024, 1, d)].session_type for d in (25, 26, 27, 28, 29)] == \
        ["NORMAL", "HOLIDAY", "WEEKEND", "WEEKEND", "NORMAL"]
    assert rows[D(2024, 1, 25)].open_ist == _dt.time(9, 15)
    assert "index_bar" in json.loads(rows[D(2024, 1, 26)].note)
    assert [c for c in cal.calls if c.startswith("holiday_on")] == ["holiday_on:2024-01-26"]


async def test_past_weekday_without_bar_or_holiday_is_refused(db_session, tmp_path):
    cal = _GenericPast(set(), {D(2024, 1, 25): "holidays_on_ordinary_day.json"})
    rep = await _past(db_session, tmp_path, cal, {D(2024, 1, 24)}, D(2024, 1, 25),
                      D(2024, 1, 25))
    assert rep.status == "FAILED" and not await _rows(db_session)


async def test_past_weekend_with_a_bar_is_a_special_session(db_session, tmp_path):
    cal = _GenericPast(set(), {D(2024, 1, 27): "holidays_on_ordinary_day.json"})
    rep = await _past(db_session, tmp_path, cal, {D(2024, 1, 27)}, D(2024, 1, 27),
                      D(2024, 1, 27))
    assert rep.status == "COMPLETE", rep.anomalies
    r = (await _rows(db_session))[D(2024, 1, 27)]
    assert (r.is_trading_day, r.session_type, r.open_ist) == (True, "SPECIAL", None)


async def test_past_date_before_the_index_history_is_refused(db_session, tmp_path):
    cal = _GenericPast(set(), {})
    rep = await _past(db_session, tmp_path, cal, {D(2024, 1, 29)}, D(2024, 1, 25),
                      D(2024, 1, 25))
    assert rep.status == "FAILED"


async def test_pre_2023_closure_needs_market_wide_evidence(db_session, tmp_path):
    """Upstox's holiday API is empty before 2023 (measured). A bar-less weekday
    is a HOLIDAY only with market-wide evidence; without it, refused."""
    cal = _GenericPast(set(), {D(2024, 1, 26): "holidays_on_ordinary_day.json"})
    bars = {D(2024, 1, 25), D(2024, 1, 29)}
    rep = await ingest_calendar(db_session, date_from=D(2024, 1, 25), date_to=D(2024, 1, 29),
                                holidays=cal.holidays, timings=cal.timings,
                                store=PayloadStore(tmp_path), commit=True, token=TOKEN,
                                holiday_on=cal.holiday_on, past_before=D(2026, 9, 24),
                                index_bar_dates=bars, market_closed_dates={D(2024, 1, 26)})
    assert rep.status == "COMPLETE", rep.anomalies
    r = (await _rows(db_session))[D(2024, 1, 26)]
    assert r.session_type == "HOLIDAY" and "closure_basis" in json.loads(r.note)
