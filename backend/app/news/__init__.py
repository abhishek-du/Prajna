"""Multi-source news (decisions NEWS-*, 2026-09-28).

A source adapter turns a feed into item observations (pure); the collector
polls politely (conditional GET, per-source interval honouring the feed's own
ttl, jitter, backoff, circuit breaker) and records either:

  DRY_RUN     local evidence files only (var/news/dryrun); no database write
  SHADOW      the news_* tables (locked: app.news.locks), invisible to Stage 2/3/API
  PRODUCTION  not available yet (no Stage 2 view reads news_* tables)

knowable_at of an item is when PRAJNA first saw it (discovered_at), never the
publisher's timestamp. Enrichments (classification, entity links) are
versioned rows with their own knowable_at. A source failure never touches
market-data ingestion: the collector is its own process with its own lock.
"""
