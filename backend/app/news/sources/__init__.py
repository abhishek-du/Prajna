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
    status: str                       # PILOT / PLANNED / UNSUPPORTED
    compliance: str                   # PENDING / APPROVED / REJECTED
    content_policy: str
    note: str = ""


SOURCES: dict[str, Source] = {s.key: s for s in (
    Source(nse_announcements.KEY, "NSE corporate announcements", "RSS", nse_announcements.URL,
           "A", nse_announcements.parse, 300, 900, 1800, "PILOT", "PENDING",
           "metadata + URL + feed description; PDF attachment not fetched",
           "feed <ttl> is 5 min: never polled faster; conditional GET"),
    Source("ET_STOCKS_RSS", "Economic Times - stocks news", "RSS",
           "https://economictimes.indiatimes.com/markets/stocks/news/rssfeeds/2146842.cms",
           "A", None, 120, 600, 1800, "PLANNED", "PENDING", "metadata + URL + description"),
    Source("BS_MARKETS_RSS", "Business Standard - markets", "RSS",
           "https://www.business-standard.com/rss/markets-106.rss",
           "B", None, 180, 900, 1800, "PLANNED", "PENDING", "metadata + URL + description"),
    Source("BL_MARKETS_RSS", "Hindu BusinessLine - markets", "RSS",
           "https://www.thehindubusinessline.com/markets/feeder/default.rss",
           "B", None, 180, 900, 1800, "PLANNED", "PENDING", "metadata + URL + description"),
    Source("MINT_MARKETS_RSS", "Livemint - markets", "RSS", "https://www.livemint.com/rss/markets",
           "B", None, 180, 900, 1800, "PLANNED", "PENDING", "metadata + URL + description"),
    Source("CNBCTV18_NEWS_SITEMAP", "CNBC-TV18 Google-News sitemap", "SITEMAP",
           "https://www.cnbctv18.com/commonfeeds/v1/cne/sitemap/google-news.xml",
           "C", None, 300, 900, 3600, "PLANNED", "PENDING", "metadata + URL"),
    Source("MONEYCONTROL", "Moneycontrol", "RSS", "https://www.moneycontrol.com/rss/",
           "-", None, 0, 0, 0, "UNSUPPORTED", "REJECTED", "none",
           "HTTP 403 on robots.txt and RSS (bot protection); no bypass"),
    Source("ZEE_BUSINESS", "Zee Business", "RSS", "https://www.zeebiz.com/",
           "-", None, 0, 0, 0, "UNSUPPORTED", "REJECTED", "none",
           "HTTP 403 on robots.txt and RSS (bot protection); no bypass"),
    Source("REUTERS", "Reuters", "-", "https://www.reuters.com/",
           "-", None, 0, 0, 0, "UNSUPPORTED", "REJECTED", "none",
           "robots.txt Disallow: / for all agents; only a licensed feed would do"),
)}
