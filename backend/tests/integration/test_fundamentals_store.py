"""Fundamentals F1 / F2 / F4 / F5b store (migration 0023; docs/STAGE1_FUNDAMENTALS_RND.md)."""

from __future__ import annotations

import datetime as _dt
import uuid

import pytest
from sqlalchemy import text

from app.fundamentals import store as FS
from tests.support.stage2_seed import _payload, _run

pytestmark = [pytest.mark.db, pytest.mark.integration]

TOKEN = "test-token-not-a-real-secret"
UTC = _dt.UTC
T0 = _dt.datetime(2026, 10, 19, 8, 0, tzinfo=UTC)
KEY, ISIN = "NSE_EQ|INE192A01025", "INE192A01025"
KEY2, ISIN2 = "NSE_EQ|INE995Z01010", "INE995Z01010"


async def _seed(s):
    rid = await _run(s, "instrument.current", source="UPSTOX_ASSETS")
    sha = await _payload(s, rid, "UPSTOX_ASSETS")
    for key, sym, isin in ((KEY, "TATACONSUM", ISIN), (KEY2, "LTTSX", ISIN2)):
        await s.execute(text("""insert into instrument (instrument_key, segment, exchange,
            trading_symbol, isin, instrument_type, valid_from, source, run_id, payload_sha256,
            fetched_at, knowable_at, knowable_at_basis) values (:k, 'NSE_EQ', 'NSE', :sym,
            :isin, 'EQ', '2026-09-01', 'UPSTOX_ASSETS', :r, :h, :f, :f, 't')"""),
            {"k": key, "sym": sym, "isin": isin, "r": rid, "h": sha, "f": T0 - _dt.timedelta(days=5)})
    nrun = await _run(s, "news.poll", source="NSE_ANNOUNCEMENTS")
    pid = (await s.execute(text("""insert into news_poll (source, mode, run_id, started_at,
        finished_at, outcome) values ('NSE_ANNOUNCEMENTS', 'SHADOW', :r, :t, :t, 'OK')
        returning id"""), {"r": nrun, "t": T0 - _dt.timedelta(days=1)})).scalar()
    return pid


async def _news(s, pid, *, source, title, summary=None, category=None, published=None,
                knowable=None, links=((KEY, 0.9),)):
    k = knowable or T0
    nid = (await s.execute(text("""insert into news_item (source, source_article_id, url,
        canonical_url, title, title_norm_hash, summary, publisher, category_raw, published_at,
        discovered_at, knowable_at, backlog, content_available, first_poll_id, content_sha256,
        payload_sha256, content_fetch_status) values (:src, :u, :u, :u, :ti, 'h', :su, 'p',
        :c, :pub, :k, :k, false, false, :p, 'c', 'p', 'NOT_AVAILABLE') returning id"""),
        {"src": source, "u": f"https://x/{uuid.uuid4()}", "ti": title, "su": summary,
         "c": category, "pub": published or k, "k": k, "p": pid})).scalar()
    for key, conf in links:
        await s.execute(text("""insert into news_entity_link (item_id, instrument_key, method,
            confidence, matched_text, reason, version, mapped_at, knowable_at) values
            (:i, :k, 'COMPANY_NAME', :c, 'x', 'x', 'v', :t, :t)"""),
            {"i": nid, "k": key, "c": conf, "t": k + _dt.timedelta(minutes=1)})
    return nid


INTIM = ("TATA CONSUMER PRODUCTS LIMITED has informed the Exchange about Board Meeting to be "
         "held on 26-Oct-2026 to consider and approve the Quarterly Unaudited Financial results "
         "of the Company for the period ended September 2026 and Other business.")
OUTCOME = ("TATA CONSUMER PRODUCTS LIMITED has submitted to the Exchange, the financial "
           "results for the period ended September 30, 2026.")


async def test_events_are_extracted_once_and_point_in_time(db_session):
    s = db_session
    pid = await _seed(s)
    await _news(s, pid, source="NSE_ANNOUNCEMENTS", title="TATA CONSUMER PRODUCTS LIMITED",
                summary=INTIM, category="Board Meeting Intimation")
    await _news(s, pid, source="NSE_ANNOUNCEMENTS", title="TATA CONSUMER PRODUCTS LIMITED",
                summary=OUTCOME, category="Outcome of Board Meeting",
                knowable=T0 + _dt.timedelta(days=7))
    await _news(s, pid, source="NSE_ANNOUNCEMENTS", title="X", summary="consider Fund raising",
                category="Board Meeting Intimation")
    await _news(s, pid, source="ET_STOCKS_RSS", links=((KEY2, 0.8),),     # news links: 0.8
                title="LTTS Q2 results: Net profit jumps 54%, beats estimates")
    await _news(s, pid, source="ET_STOCKS_RSS", links=((KEY, 0.95), (KEY2, 0.95)),
                title="TCS, LTTS Q2 results beat estimates")        # two names: ambiguous
    dry = await FS.extract_events(s)
    assert dry["inserted"] == 0 and dry["by_kind"] == {"INTIMATION": 1, "OUTCOME": 1,
                                                       "ESTIMATE_NEWS": 1}
    with pytest.raises(Exception):
        await FS.extract_events(s, commit=True, token="wrong")
    got = await FS.extract_events(s, commit=True, token=TOKEN)
    assert got["inserted"] == 3
    rows = {r.kind: r for r in (await s.execute(text("""select kind, isin, meeting_date,
        period_end, verdict, event_at, knowable_at from results_event"""))).all()}
    i = rows["INTIMATION"]
    assert i.isin == ISIN and i.meeting_date == _dt.date(2026, 10, 26)
    assert i.period_end == _dt.date(2026, 9, 30)
    assert i.knowable_at == T0 + _dt.timedelta(minutes=1)        # when the link existed
    assert i.event_at == T0
    assert rows["ESTIMATE_NEWS"].verdict == "BEAT"
    again = await FS.extract_events(s, commit=True, token=TOKEN)
    assert again["inserted"] == 0 and again["candidates"] == 2   # the two non-events
    with pytest.raises(Exception, match="append-only"):
        await s.execute(text("update results_event set verdict = 'MISS'"))


class _Batch:
    def __init__(self, isins):
        self.isins, self.status, self.run_id = isins, "COMPLETE", None
        self.inserted, self.error = 3, None


class _Rep:
    def __init__(self, isins):
        self.results, self.stopped = [_Batch(isins)], None


async def test_refresh_follows_outcomes_once(db_session, monkeypatch):
    s = db_session
    pid = await _seed(s)
    await _news(s, pid, source="NSE_ANNOUNCEMENTS", title="T", summary=OUTCOME,
                category="Outcome of Board Meeting", knowable=_dt.datetime.now(UTC)
                - _dt.timedelta(hours=3))
    await FS.extract_events(s, commit=True, token=TOKEN)
    calls = []

    class FakeIngestor:
        def __init__(self, *a, **kw):
            assert kw["batch"] == 1 and kw["commit"]

        async def run(self, isins):
            calls.append(isins)
            return _Rep(isins)

    import app.ingest.fundamentals as F
    monkeypatch.setattr(F, "FundamentalsIngestor", FakeIngestor)
    dry = await FS.refresh(s, None, None)
    assert dry["due"] == 1 and dry["isins"] == [ISIN] and not calls
    got = await FS.refresh(s, None, None, commit=True, token=TOKEN)
    assert got["refreshed"] == 1 and got["inserted"] == 3 and calls == [[ISIN]]
    assert (await FS.refresh(s, None, None, commit=True, token=TOKEN))["due"] == 0
    rep = await FS.fund_report(s)
    assert rep["status"] in ("PENDING", "FAIL") and rep["checks"]["sessions"] is False
    assert rep["snapshots_knowable_before_fetch"] == 0


CSV = (b"\xef\xbb\xbfSYMBOL,COMPANY NAME,AUDITED,PERIOD ENDED,RELATING TO,"
       b"BROADCAST DATE/TIME\n"
       b"TATACONSUM,Tata Consumer,Un-Audited,30-Jun-2023,First Quarter,"
       b"25-Jul-2023 16:10:05\n"
       b"NOSUCH,Nobody,Audited,31-Mar-2023,Annual,02-May-2023 11:00:00\n"
       b"TATACONSUM,Tata Consumer,Un-Audited,30-Sep-2023,,\n")


async def test_results_csv_import(db_session):
    s = db_session
    await _seed(s)
    with pytest.raises(FS.CsvRefused):
        await FS.import_results_csv(s, b"a,b\n1,2\n", "bad.csv")
    dry = await FS.import_results_csv(s, CSV, "nse.csv")
    assert dry["rows"] == 2 and dry["bad"]["no_broadcast"] == 1
    assert dry["unmapped_symbols"] == 1 and dry["events"] == 1
    got = await FS.import_results_csv(s, CSV, "nse.csv", commit=True, token=TOKEN)
    assert got["inserted"] == 1
    r = (await s.execute(text("""select kind, period_end, period_kind, event_at, knowable_at,
        provenance from results_event"""))).one()
    assert r.kind == "HISTORICAL_FILING" and r.period_end == _dt.date(2023, 6, 30)
    assert r.period_kind == "Q" and r.event_at.date() == _dt.date(2023, 7, 25)
    assert r.knowable_at > r.event_at and r.provenance["file"] == "nse.csv"
    assert (await FS.import_results_csv(s, CSV, "nse.csv", commit=True,
                                        token=TOKEN))["inserted"] == 0


# the real exports (2026-10-23): Integrated Filing has SYMBOL + QUARTER END DATE; Financial
# Results has company names only and the exchange's dissemination time
IF_CSV = ('﻿"SYMBOL \n","COMPANY NAME \n","QUARTER END DATE \n","TYPE OF SUBMISSION \n",'
          '"CONSOLIDATED / STANDALONE \n","BROADCAST DATE/TIME \n",'
          '"EXCHANGE DISSEMINATION TIME \n"\n'
          '"TATACONSUM","Tata Consumer Products Limited","30-SEP-2026","Original",'
          '"Consolidated","23-Oct-2026 13:45:17","23-Oct-2026 13:48:53"\n').encode()
FR_CSV = ('﻿"COMPANY NAME","CONSOLIDATED / NON-CONSOLIDATED","PERIOD","PERIOD ENDED",'
          '"RELATING TO","Exchange Received Time","Exchange Dissemination Time"\n'
          '"TATA CONSUMER PRODUCTS LTD.","Consolidated","Quarterly","30-Jun-2024",'
          '"First Quarter","06-Aug-2024 14:07:24","06-Aug-2024 14:07:55"\n'
          '"Gone Away Limited","Consolidated","Quarterly","30-Jun-2016","First Quarter",'
          '"06-Aug-2016 14:07:24","06-Aug-2016 14:07:55"\n').encode()


async def test_results_csv_real_exports(db_session):
    s = db_session
    await _seed(s)
    got = await FS.import_results_csv(s, IF_CSV, "if.csv", commit=True, token=TOKEN)
    assert got["events"] == 1 and got["inserted"] == 1
    r = (await s.execute(text("""select period_end, period_kind, event_at, provenance
        from results_event"""))).one()
    assert r.period_end == _dt.date(2026, 9, 30) and r.period_kind == "Q"
    from app.core.clock import IST
    assert r.event_at.astimezone(IST).strftime("%H:%M:%S") == "13:48:53"   # dissemination
    assert r.provenance["basis"] == "Consolidated" and r.provenance["submission"] == "Original"
    with pytest.raises(FS.CsvRefused):                                # no symbol, no names
        FS.map_columns(["PERIOD ENDED", "Exchange Dissemination Time"])
    names = FS.names_from_csv(IF_CSV)
    assert names == {"tata consumer products": "TATACONSUM"}
    fr = await FS.import_results_csv(s, FR_CSV, "fr.csv", names=names)
    assert fr["mapped_by_name"] == 1 and fr["no_name_match"] == 1 and fr["events"] == 1
