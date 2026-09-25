"""knowable_at — the contract V1 only had inside a research script."""

from __future__ import annotations

import datetime as _dt

import pytest

from app.contracts import knowable as K
from app.core.clock import IST, UTC


def _utc(y, m, d, hh=0, mm=0):
    return _dt.datetime(y, m, d, hh, mm, tzinfo=UTC)


class TestDailyBar:
    def test_is_not_the_bar_label(self):
        """The defect that produced V1's entire legacy daily series."""
        session = _dt.date(2026, 9, 1)
        k = K.for_daily_bar(session, _utc(2026, 9, 1, 12, 0))
        label_as_instant = _dt.datetime.combine(session, _dt.time(0, 0), tzinfo=IST)
        assert k.at > label_as_instant.astimezone(UTC)

    def test_never_earlier_than_session_close(self):
        session = _dt.date(2026, 9, 1)
        close_utc = _dt.datetime.combine(session, _dt.time(15, 30), tzinfo=IST).astimezone(UTC)
        # Even a fetch that somehow precedes the close cannot pull it earlier.
        assert K.for_daily_bar(session, close_utc - _dt.timedelta(hours=3)).at >= close_utc

    def test_is_unverified_until_measured(self):
        """Constraint #9: B1 is open, so this must not claim precision."""
        k = K.for_daily_bar(_dt.date(2026, 9, 1), _utc(2026, 9, 1, 12, 0))
        assert k.verified is False
        assert "UNVERIFIED (B1)" in k.basis

    def test_verified_finality_never_moves_knowable_before_the_fetch(self):
        """TIMING-B2: B1 verified = the bar is final from the close; Prajna still
        only KNEW it at the fetch (the stricter rule replaced 'exact close')."""
        session = _dt.date(2026, 9, 1)
        k = K.for_daily_bar(session, _utc(2026, 9, 2), settlement_lag_verified=True)
        assert k.verified is True
        assert k.at == _utc(2026, 9, 2)


class TestIntradayBar:
    def test_bar_is_not_knowable_at_its_start(self):
        start = _utc(2026, 9, 1, 3, 45)
        k = K.for_intraday_bar(start, "1m", start, publication_lag_verified=True)
        assert k.at == start + _dt.timedelta(minutes=1)

    def test_unknown_timeframe_raises_rather_than_guessing(self):
        """V1 defaulted an unknown interval to DAILY, silently."""
        with pytest.raises(ValueError, match="refusing to guess"):
            K.for_intraday_bar(_utc(2026, 9, 1), "5min", _utc(2026, 9, 1))

    def test_is_unverified_until_lag_measured(self):
        k = K.for_intraday_bar(_utc(2026, 9, 1, 3, 45), "1m", _utc(2026, 9, 1, 12))
        assert k.verified is False and "UNVERIFIED (B2)" in k.basis


class TestPreopen:
    def test_is_verified_and_equals_vendor_timestamp(self):
        """A live push stream has no publication lag to measure."""
        vts = _utc(2026, 9, 22, 3, 39, )
        k = K.for_preopen_tick(vts)
        assert k.verified is True and k.at == vts

    def test_never_falls_back_to_fetched_at(self):
        vts = _utc(2026, 9, 22, 3, 39)
        fetched = vts + _dt.timedelta(seconds=4)
        assert K.for_preopen_tick(vts).at == vts != fetched


class TestAnnouncedFacts:
    def test_uses_announcement_time_when_supplied(self):
        ann, fetched = _utc(2026, 8, 1, 10), _utc(2026, 9, 1)
        k = K.for_announced_fact(ann, fetched, what="corporate_action")
        assert k.verified is True and k.at == ann

    def test_falls_back_honestly_when_absent(self):
        fetched = _utc(2026, 9, 1)
        k = K.for_announced_fact(None, fetched, what="corporate_action")
        assert k.verified is False and k.at == fetched

    def test_snapshot_download_is_unverified(self):
        k = K.for_snapshot_download(_utc(2026, 9, 1))
        assert k.verified is False


class TestLookAheadGuard:
    def test_boundary_is_excluded(self):
        """Strictly '<'. A fact knowable exactly at T is not usable at T."""
        t = _utc(2026, 9, 1, 10)
        with pytest.raises(K.LookAheadViolation):
            K.assert_knowable_before(t, t, "boundary")

    def test_future_fact_rejected(self):
        with pytest.raises(K.LookAheadViolation, match="LOOK-AHEAD"):
            K.assert_knowable_before(_utc(2026, 9, 2), _utc(2026, 9, 1), "tomorrow")

    def test_past_fact_allowed(self):
        K.assert_knowable_before(_utc(2026, 9, 1, 9), _utc(2026, 9, 1, 10), "earlier")

    def test_naive_datetime_rejected(self):
        with pytest.raises(ValueError, match="naive"):
            K.assert_knowable_before(_dt.datetime(2026, 9, 1), _utc(2026, 9, 2), "naive")
