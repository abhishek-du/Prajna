"""The multi-source news schedule in ops/cron/prajna.cron (go-live 2026-09-29):
a collection supervisor (flock-protected restarts) for the 7 accepted sources,
never Indian Express, never a token on the command line, and a separate
read-only reconciliation after the collector's deadline."""

from __future__ import annotations

import pathlib

CRON = pathlib.Path(__file__).resolve().parents[2] / "ops" / "cron" / "prajna.cron"
ACCEPTED = {"NSE_ANNOUNCEMENTS", "SEBI_RSS", "ET_STOCKS_RSS", "BS_MARKETS_RSS", "BL_MARKETS_RSS",
            "MINT_MARKETS_RSS", "CNBCTV18_NEWS_SITEMAP"}


def _active():
    return [ln for ln in CRON.read_text().splitlines() if ln.strip() and not ln.startswith("#")
            and not ln.split("=")[0].isupper()]


def test_collection_supervisor_covers_the_day_and_stops_before_the_deadline():
    jobs = [ln for ln in _active() if "news_collect.sh" in ln]
    assert [" ".join(j.split()[:5]) for j in jobs] == ["*/15 6-22 * * *", "0,15 23 * * *"]
    for j in jobs:
        assert "--mode PRODUCTION" in j and "--until 23:30" in j and "--token-from-dotenv" in j
        sources = set(j.split("--sources ")[1].split()[0].split(","))
        assert sources == ACCEPTED                          # Indian Express is not enabled
        assert "--token " not in j and "PRAJNA_WRITE_TOKEN" not in j


def test_reconciliation_is_separate_and_after_the_collector():
    jobs = [ln for ln in _active() if "news_reconcile" in ln]
    assert len(jobs) == 1 and jobs[0].split()[:5] == ["45", "23", "*", "*", "*"]
    assert "news_collect" not in jobs[0] and "--mode PRODUCTION" in jobs[0]


def test_the_collector_is_single_instance():
    rb = (CRON.parent.parent / "runbooks" / "news_collect.sh").read_text()
    assert "flock -n 9" in rb and "NEWS_COLLECT_SKIP" in rb
