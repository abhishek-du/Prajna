"""News source registry. Adding a source = an adapter module + an entry here.

Every source carries its compliance status (decision NEWS-COMPLIANCE): until
APPROVED, only DRY_RUN is allowed for it. Intervals come from the source's own
constraints; the collector never polls faster than the feed's <ttl>.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.news.model import ParsedFeed
from app.news.sources import nse_announcements
from app.news.sources.rss import news_sitemap_parser, rss_parser, sebi_parser


@dataclass(frozen=True, slots=True)
class Source:
    key: str
    name: str
    kind: str                         # RSS / SITEMAP / API
    url: str
    tier: str
    parse: Callable[[bytes], ParsedFeed] | None
    market_interval_s: int            # 09:00-15:45 IST on weekdays
    off_interval_s: int
    weekend_interval_s: int
    status: str                       # PILOT / ADAPTER / PLANNED / UNSUPPORTED
    compliance: str                   # PENDING / APPROVED / REJECTED
    content_policy: str
    note: str = ""
    # EXCHANGE (filings: subject + filer) / HEADLINE (media) / REGULATOR (SEBI)
    enrich: str = "HEADLINE"
    flag: str | None = None           # the per-source write flag (Settings attribute)
    priority: int = 3                 # 1 = primary (exchange/regulator) .. 3 = media
    # article bodies may be fetched (app.news.content) only when this is True AND the
    # terms review is APPROVED; False for every source until that review exists
    body_allowed: bool = False


_FLAGS = {  # source -> (per-source write flag, priority)
    "NSE_ANNOUNCEMENTS": ("PRAJNA_NEWS_NSE_ENABLED", 1),
    "ET_STOCKS_RSS": ("PRAJNA_NEWS_ET_ENABLED", 3),
    "BS_MARKETS_RSS": ("PRAJNA_NEWS_BS_ENABLED", 3),
    "BL_MARKETS_RSS": ("PRAJNA_NEWS_BL_ENABLED", 3),
    "MINT_MARKETS_RSS": ("PRAJNA_NEWS_MINT_ENABLED", 3),
    "CNBCTV18_NEWS_SITEMAP": ("PRAJNA_NEWS_CNBC_ENABLED", 3),
    "INDIANEXPRESS_BUSINESS_RSS": ("PRAJNA_NEWS_IE_ENABLED", 3),
    "SEBI_RSS": ("PRAJNA_NEWS_SEBI_ENABLED", 1),
}

_BASE: tuple[Source, ...] = (
    Source(nse_announcements.KEY, "NSE corporate announcements", "RSS", nse_announcements.URL,
           "A", nse_announcements.parse, 300, 900, 1800, "PILOT", "PENDING",
           "metadata + URL + feed description; PDF attachment not fetched",
           "feed <ttl> is 5 min: never polled faster; conditional GET", "EXCHANGE"),
    Source("ET_STOCKS_RSS", "Economic Times - stocks news", "RSS",
           "https://economictimes.indiatimes.com/markets/stocks/news/rssfeeds/2146842.cms",
           "A", rss_parser("Economic Times"), 120, 600, 1800, "ADAPTER", "PENDING",
           "metadata + URL + description", "conditional GET (ETag)"),
    Source("BS_MARKETS_RSS", "Business Standard - markets", "RSS",
           "https://www.business-standard.com/rss/markets-106.rss",
           "B", rss_parser("Business Standard"), 180, 900, 1800, "ADAPTER", "PENDING",
           "metadata + URL + description", "conditional GET (ETag); much content paywalled"),
    Source("BL_MARKETS_RSS", "Hindu BusinessLine - markets", "RSS",
           "https://www.thehindubusinessline.com/markets/feeder/default.rss",
           "B", rss_parser("BusinessLine"), 180, 900, 1800, "ADAPTER", "PENDING",
           "metadata + URL + description", "feed <ttl> is 60 min: polled at most hourly"),
    Source("MINT_MARKETS_RSS", "Livemint - markets", "RSS", "https://www.livemint.com/rss/markets",
           "B", rss_parser("Mint"), 180, 900, 1800, "ADAPTER", "PENDING",
           "metadata + URL + description", "no conditional GET (full download each poll)"),
    Source("CNBCTV18_NEWS_SITEMAP", "CNBC-TV18 Google-News sitemap", "SITEMAP",
           "https://www.cnbctv18.com/commonfeeds/v1/cne/sitemap/google-news.xml",
           "C", news_sitemap_parser("CNBC-TV18"), 300, 900, 3600, "ADAPTER", "PENDING",
           "metadata + URL + keywords", "~270 KB per poll, no conditional GET: slow cadence"),
    Source("INDIANEXPRESS_BUSINESS_RSS", "Indian Express - business", "RSS",
           "https://indianexpress.com/section/business/feed/",
           "B", rss_parser("Indian Express"), 180, 900, 1800, "ADAPTER", "PENDING",
           "metadata + URL (the feed carries no description)",
           "~200 KB, 200 items; conditional GET (ETag). The market-section feed is stale "
           "(newest item 2026-09-21), so the business feed is used"),
    Source("SEBI_RSS", "SEBI - press releases, circulars, orders", "RSS",
           "https://www.sebi.gov.in/sebirss.xml",
           "A", sebi_parser(), 3600, 3600, 3600, "ADAPTER", "PENDING",
           "metadata + URL (public regulatory publications)",
           "<ttl>60</ttl>: hourly; pubDate is a DATE only, so no publication time or "
           "latency is claimed", "REGULATOR"),
    Source("MONEYCONTROL", "Moneycontrol", "RSS", "https://www.moneycontrol.com/rss/",
           "-", None, 0, 0, 0, "UNSUPPORTED", "REJECTED", "none",
           "HTTP 403 on robots.txt and RSS (bot protection); no bypass"),
    Source("ZEE_BUSINESS", "Zee Business", "RSS", "https://www.zeebiz.com/",
           "-", None, 0, 0, 0, "UNSUPPORTED", "REJECTED", "none",
           "HTTP 403 on robots.txt and RSS (bot protection); no bypass"),
    Source("REUTERS", "Reuters", "-", "https://www.reuters.com/",
           "-", None, 0, 0, 0, "UNSUPPORTED", "REJECTED", "none",
           "robots.txt Disallow: / for all agents; only a licensed feed would do"),
)


def _with_flags(s: Source) -> Source:
    f = _FLAGS.get(s.key)
    if not f:
        return s
    fields = {k: getattr(s, k) for k in s.__slots__}
    return Source(**{**fields, "flag": f[0], "priority": f[1]})


SOURCES: dict[str, Source] = {s.key: _with_flags(s) for s in _BASE}
