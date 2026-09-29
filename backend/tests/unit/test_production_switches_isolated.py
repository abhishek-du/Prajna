"""Tests never inherit production execution switches from backend/.env (go-live
2026-09-29: PRAJNA_STAGE3_ENABLED=true in .env made the "defaults refuse" tests
fail). The conftest guard pins them to the locked defaults for the test process."""

from __future__ import annotations

import os

from app.core.config import get_settings


def test_stage3_switches_are_the_locked_defaults_inside_tests():
    assert os.environ["PRAJNA_STAGE3_ENABLED"] == "false"
    assert os.environ["PRAJNA_STAGE3_BACKFILL_ENABLED"] == "false"
    st = get_settings()
    assert st.PRAJNA_STAGE3_ENABLED is False and st.PRAJNA_STAGE3_BACKFILL_ENABLED is False


def test_news_write_switches_are_the_locked_defaults_inside_tests():
    st = get_settings()
    for f in ("NSE", "ET", "BS", "BL", "MINT", "CNBC", "IE", "SEBI", "MULTI_SOURCE"):
        assert getattr(st, f"PRAJNA_NEWS_{f}_ENABLED") is False, f
