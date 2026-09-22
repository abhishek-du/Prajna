from __future__ import annotations

import pytest

from app.contracts import identity as I
from app.contracts import timeframe as T


class TestInstrumentIdentity:
    def test_parses_upstox_key(self):
        k = I.parse_instrument_key("NSE_EQ|INE002A01018")
        assert (k.segment, k.token, k.is_isin_keyed) == ("NSE_EQ", "INE002A01018", True)

    def test_index_key_is_name_keyed(self):
        k = I.parse_instrument_key("NSE_INDEX|India VIX")
        assert k.segment == "NSE_INDEX" and k.is_isin_keyed is False

    def test_malformed_key_raises(self):
        with pytest.raises(ValueError, match="malformed"):
            I.parse_instrument_key("RELIANCE")

    @pytest.mark.parametrize("isin", ["INE002A01018", "INF204KB14I2", "IN9470A01018"])
    def test_isin_check_is_structural_only(self, isin):
        """Verified 2026-09-22 against the live Upstox master: 351 tradeable
        instruments carry INF ISINs (ETFs, incl. NIFTYBEES=INF204KB14I2) and 2
        carry IN9. An 'INE-only' rule would silently drop all of them."""
        assert I.is_valid_isin(isin) is True

    @pytest.mark.parametrize("bad", ["", None, "US0378331005", "INE002A0101", "ine002a01018x"])
    def test_rejects_non_isin(self, bad):
        assert I.is_valid_isin(bad) is False

    @pytest.mark.parametrize("series", ["EQ", "BE", "SM", "BZ", "ST", "IV"])
    def test_tradeable_series(self, series):
        assert I.is_tradeable_equity("NSE_EQ", series) is True

    @pytest.mark.parametrize("series", ["SG", "N0", "TB", "GB", "ND"])
    def test_debt_and_govt_excluded(self, series):
        assert I.is_tradeable_equity("NSE_EQ", series) is False

    def test_derivative_segment_excluded(self):
        assert I.is_tradeable_equity("NSE_FO", "EQ") is False


class TestTimeframe:
    def test_upstox_interval_mapping(self):
        assert T.upstox_interval("1d") == ("days", 1)
        assert T.upstox_interval("15m") == ("minutes", 15)
        assert T.upstox_interval("1h") == ("hours", 1)

    def test_unknown_timeframe_raises_not_defaults(self):
        """V1: _INTERVAL_MAP.get(interval, _INTERVAL_MAP['1d']) — a typo
        silently returned daily bars labelled with the typo."""
        with pytest.raises(ValueError, match="refusing to fall back"):
            T.upstox_interval("5min")

    def test_session_date_is_ist_calendar_date(self):
        import datetime as dt
        from app.core.clock import UTC
        # 03:45 UTC = 09:15 IST, the NSE open, same IST date.
        assert T.session_date_for_intraday(
            dt.datetime(2026, 9, 1, 3, 45, tzinfo=UTC)) == dt.date(2026, 9, 1)
        # 18:30 UTC on 31-Aug = 00:00 IST on 1-Sep. This is exactly the
        # conversion that produced V1's one-day-offset legacy series.
        assert T.session_date_for_intraday(
            dt.datetime(2026, 8, 31, 18, 30, tzinfo=UTC)) == dt.date(2026, 9, 1)

    def test_ohlc_validation(self):
        T.validate_bar(10, 12, 9, 11, 100)
        with pytest.raises(ValueError, match="high"):
            T.validate_bar(10, 8, 9, 11, 100)
        with pytest.raises(ValueError, match="negative volume"):
            T.validate_bar(10, 12, 9, 11, -1)
