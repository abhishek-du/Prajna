# Multi-source news acceptance

**Generated:** 2026-09-28T14:51:52.776224+00:00 by `prajna acceptance news` (read-only; regenerate, do not edit).

## Overall: **NOT PASSED**

a PASS unlocks nothing by itself: writes also need the per-source flag, terms APPROVED, Stage 2 PASS and a token.

| Source | Status | EVIDENCE | LATENCY | HEALTH | POLITENESS | MAPPING | TERMS | PIT |
|---|---|---|---|---|---|---|---|---|
| NSE_ANNOUNCEMENTS | **PENDING** | PENDING | PASS | PASS | PENDING | PENDING | PENDING | PENDING |
| ET_STOCKS_RSS | **PENDING** | PENDING | PASS | PASS | PENDING | PENDING | PENDING | PENDING |
| BS_MARKETS_RSS | **PENDING** | PENDING | PASS | PASS | PENDING | PENDING | PENDING | PENDING |
| BL_MARKETS_RSS | **PENDING** | PENDING | PASS | PASS | PENDING | PENDING | PENDING | PENDING |
| MINT_MARKETS_RSS | **PENDING** | PENDING | PASS | PASS | PENDING | PENDING | PENDING | PENDING |
| CNBCTV18_NEWS_SITEMAP | **PENDING** | PENDING | PASS | PASS | PENDING | PENDING | PENDING | PENDING |
| INDIANEXPRESS_BUSINESS_RSS | **PENDING** | PENDING | PENDING | PASS | PENDING | PENDING | PENDING | PENDING |
| SEBI_RSS | **PENDING** | PENDING | NOT_MEASURABLE | PASS | PENDING | PENDING | PENDING | PENDING |

## Per source

### NSE_ANNOUNCEMENTS: PENDING

```json
{
 "criteria": {
  "EVIDENCE": {
   "status": "PENDING",
   "evidence": {
    "full_market_sessions": [],
    "polls": 21
   }
  },
  "LATENCY": {
   "status": "PASS",
   "evidence": {
    "discovery_s": {
     "n": 1483,
     "p50": 525.3,
     "p90": 1278.0,
     "p95": 1602.4,
     "p99": 2005.4,
     "max": 2075.4
    },
    "market_hours": {
     "n": 0,
     "p50": null,
     "p90": null,
     "p95": null,
     "p99": null,
     "max": null
    }
   }
  },
  "HEALTH": {
   "status": "PASS",
   "evidence": {
    "blocked": 0,
    "failed": 3,
    "polls": 21,
    "health_now": "HEALTHY"
   }
  },
  "POLITENESS": {
   "status": "PENDING",
   "evidence": {
    "session_day": null,
    "min_gap_s": null,
    "floor_s": 240.0
   }
  },
  "MAPPING": {
   "status": "PENDING",
   "evidence": {
    "reason": "no reviewed mapping sample (NSE_ANNOUNCEMENTS.json); run `prajna news review-sample --source NSE_ANNOUNCEMENTS` and judge it"
   }
  },
  "TERMS": {
   "status": "PENDING",
   "evidence": {
    "terms": "PENDING"
   }
  },
  "PIT": {
   "status": "PENDING",
   "evidence": {
    "note": "run with --run-tests"
   }
  }
 },
 "summary": {
  "items": 2713,
  "live_items": 1485,
  "backlog_items": 1228,
  "mapping_rate": 0.851,
  "unresolved": 403,
  "stories": {
   "items_with_story": 1104,
   "joined_existing": 504,
   "by_method": {
    "FOUNDER": 600,
    "SAME_TITLE": 504
   }
  },
  "assessment": {
   "breaking": 12,
   "impact": {
    "LOW": 865,
    "MEDIUM": 142,
    "UNKNOWN": 82,
    "HIGH": 15
   },
   "scope": {
    "STOCK": 999,
    "UNKNOWN": 69,
    "SECTOR": 21,
    "INDEX": 13,
    "MACRO": 2
   }
  },
  "content_fetch_status": {
   "NOT_AVAILABLE": 2713
  },
  "rate_limit_events": 0,
  "errors": 3
 }
}
```

### ET_STOCKS_RSS: PENDING

```json
{
 "criteria": {
  "EVIDENCE": {
   "status": "PENDING",
   "evidence": {
    "full_market_sessions": [],
    "polls": 28
   }
  },
  "LATENCY": {
   "status": "PASS",
   "evidence": {
    "discovery_s": {
     "n": 6,
     "p50": 1250.0,
     "p90": 1778.9,
     "p95": 1954.8,
     "p99": 2095.5,
     "max": 2130.7
    },
    "market_hours": {
     "n": 0,
     "p50": null,
     "p90": null,
     "p95": null,
     "p99": null,
     "max": null
    }
   }
  },
  "HEALTH": {
   "status": "PASS",
   "evidence": {
    "blocked": 0,
    "failed": 0,
    "polls": 28,
    "health_now": "HEALTHY"
   }
  },
  "POLITENESS": {
   "status": "PENDING",
   "evidence": {
    "session_day": null,
    "min_gap_s": null,
    "floor_s": 96.0
   }
  },
  "MAPPING": {
   "status": "PENDING",
   "evidence": {
    "reason": "no reviewed mapping sample (ET_STOCKS_RSS.json); run `prajna news review-sample --source ET_STOCKS_RSS` and judge it"
   }
  },
  "TERMS": {
   "status": "PENDING",
   "evidence": {
    "terms": "PENDING"
   }
  },
  "PIT": {
   "status": "PENDING",
   "evidence": {
    "note": "run with --run-tests"
   }
  }
 },
 "summary": {
  "items": 56,
  "live_items": 6,
  "backlog_items": 50,
  "mapping_rate": 0.446,
  "unresolved": 31,
  "stories": {
   "items_with_story": 4,
   "joined_existing": 0,
   "by_method": {
    "FOUNDER": 4
   }
  },
  "assessment": {
   "breaking": 0,
   "impact": {
    "MEDIUM": 3,
    "HIGH": 1
   },
   "scope": {
    "UNKNOWN": 1,
    "MACRO": 1,
    "STOCK": 2
   }
  },
  "content_fetch_status": {
   "NOT_AVAILABLE": 56
  },
  "rate_limit_events": 0,
  "errors": 0
 }
}
```

### BS_MARKETS_RSS: PENDING

```json
{
 "criteria": {
  "EVIDENCE": {
   "status": "PENDING",
   "evidence": {
    "full_market_sessions": [],
    "polls": 19
   }
  },
  "LATENCY": {
   "status": "PASS",
   "evidence": {
    "discovery_s": {
     "n": 23,
     "p50": 847.3,
     "p90": 1151.9,
     "p95": 1158.0,
     "p99": 1185.4,
     "max": 1192.9
    },
    "market_hours": {
     "n": 0,
     "p50": null,
     "p90": null,
     "p95": null,
     "p99": null,
     "max": null
    }
   }
  },
  "HEALTH": {
   "status": "PASS",
   "evidence": {
    "blocked": 0,
    "failed": 0,
    "polls": 19,
    "health_now": "HEALTHY"
   }
  },
  "POLITENESS": {
   "status": "PENDING",
   "evidence": {
    "session_day": null,
    "min_gap_s": null,
    "floor_s": 144.0
   }
  },
  "MAPPING": {
   "status": "PENDING",
   "evidence": {
    "reason": "no reviewed mapping sample (BS_MARKETS_RSS.json); run `prajna news review-sample --source BS_MARKETS_RSS` and judge it"
   }
  },
  "TERMS": {
   "status": "PENDING",
   "evidence": {
    "terms": "PENDING"
   }
  },
  "PIT": {
   "status": "PENDING",
   "evidence": {
    "note": "run with --run-tests"
   }
  }
 },
 "summary": {
  "items": 58,
  "live_items": 23,
  "backlog_items": 35,
  "mapping_rate": 0.31,
  "unresolved": 40,
  "stories": {
   "items_with_story": 18,
   "joined_existing": 0,
   "by_method": {
    "FOUNDER": 18
   }
  },
  "assessment": {
   "breaking": 0,
   "impact": {
    "UNKNOWN": 7,
    "MEDIUM": 10,
    "LOW": 1
   },
   "scope": {
    "MACRO": 5,
    "INDEX": 1,
    "SECTOR": 1,
    "UNKNOWN": 7,
    "STOCK": 4
   }
  },
  "content_fetch_status": {
   "NOT_AVAILABLE": 58
  },
  "rate_limit_events": 0,
  "errors": 0
 }
}
```

### BL_MARKETS_RSS: PENDING

```json
{
 "criteria": {
  "EVIDENCE": {
   "status": "PENDING",
   "evidence": {
    "full_market_sessions": [],
    "polls": 8
   }
  },
  "LATENCY": {
   "status": "PASS",
   "evidence": {
    "discovery_s": {
     "n": 15,
     "p50": 636.0,
     "p90": 2068.4,
     "p95": 2416.3,
     "p99": 2974.6,
     "max": 3114.2
    },
    "market_hours": {
     "n": 0,
     "p50": null,
     "p90": null,
     "p95": null,
     "p99": null,
     "max": null
    }
   }
  },
  "HEALTH": {
   "status": "PASS",
   "evidence": {
    "blocked": 0,
    "failed": 0,
    "polls": 8,
    "health_now": "HEALTHY"
   }
  },
  "POLITENESS": {
   "status": "PENDING",
   "evidence": {
    "session_day": null,
    "min_gap_s": null,
    "floor_s": 144.0
   }
  },
  "MAPPING": {
   "status": "PENDING",
   "evidence": {
    "reason": "no reviewed mapping sample (BL_MARKETS_RSS.json); run `prajna news review-sample --source BL_MARKETS_RSS` and judge it"
   }
  },
  "TERMS": {
   "status": "PENDING",
   "evidence": {
    "terms": "PENDING"
   }
  },
  "PIT": {
   "status": "PENDING",
   "evidence": {
    "note": "run with --run-tests"
   }
  }
 },
 "summary": {
  "items": 75,
  "live_items": 15,
  "backlog_items": 60,
  "mapping_rate": 0.12,
  "unresolved": 66,
  "stories": {
   "items_with_story": 12,
   "joined_existing": 0,
   "by_method": {
    "FOUNDER": 12
   }
  },
  "assessment": {
   "breaking": 2,
   "impact": {
    "HIGH": 2,
    "MEDIUM": 7,
    "UNKNOWN": 2,
    "LOW": 1
   },
   "scope": {
    "UNKNOWN": 5,
    "SECTOR": 1,
    "MACRO": 3,
    "INDEX": 1,
    "STOCK": 2
   }
  },
  "content_fetch_status": {
   "NOT_AVAILABLE": 75
  },
  "rate_limit_events": 0,
  "errors": 0
 }
}
```

### MINT_MARKETS_RSS: PENDING

```json
{
 "criteria": {
  "EVIDENCE": {
   "status": "PENDING",
   "evidence": {
    "full_market_sessions": [],
    "polls": 21
   }
  },
  "LATENCY": {
   "status": "PASS",
   "evidence": {
    "discovery_s": {
     "n": 10,
     "p50": 372.3,
     "p90": 767.7,
     "p95": 833.5,
     "p99": 886.1,
     "max": 899.2
    },
    "market_hours": {
     "n": 0,
     "p50": null,
     "p90": null,
     "p95": null,
     "p99": null,
     "max": null
    }
   }
  },
  "HEALTH": {
   "status": "PASS",
   "evidence": {
    "blocked": 0,
    "failed": 0,
    "polls": 21,
    "health_now": "HEALTHY"
   }
  },
  "POLITENESS": {
   "status": "PENDING",
   "evidence": {
    "session_day": null,
    "min_gap_s": null,
    "floor_s": 144.0
   }
  },
  "MAPPING": {
   "status": "PENDING",
   "evidence": {
    "reason": "no reviewed mapping sample (MINT_MARKETS_RSS.json); run `prajna news review-sample --source MINT_MARKETS_RSS` and judge it"
   }
  },
  "TERMS": {
   "status": "PENDING",
   "evidence": {
    "terms": "PENDING"
   }
  },
  "PIT": {
   "status": "PENDING",
   "evidence": {
    "note": "run with --run-tests"
   }
  }
 },
 "summary": {
  "items": 45,
  "live_items": 10,
  "backlog_items": 35,
  "mapping_rate": 0.289,
  "unresolved": 32,
  "stories": {
   "items_with_story": 6,
   "joined_existing": 0,
   "by_method": {
    "FOUNDER": 6
   }
  },
  "assessment": {
   "breaking": 0,
   "impact": {
    "MEDIUM": 4,
    "UNKNOWN": 2
   },
   "scope": {
    "STOCK": 2,
    "UNKNOWN": 3,
    "MARKET": 1
   }
  },
  "content_fetch_status": {
   "NOT_AVAILABLE": 45
  },
  "rate_limit_events": 0,
  "errors": 0
 }
}
```

### CNBCTV18_NEWS_SITEMAP: PENDING

```json
{
 "criteria": {
  "EVIDENCE": {
   "status": "PENDING",
   "evidence": {
    "full_market_sessions": [],
    "polls": 20
   }
  },
  "LATENCY": {
   "status": "PASS",
   "evidence": {
    "discovery_s": {
     "n": 55,
     "p50": 773.0,
     "p90": 1201.5,
     "p95": 1293.3,
     "p99": 1408.5,
     "max": 1474.4
    },
    "market_hours": {
     "n": 0,
     "p50": null,
     "p90": null,
     "p95": null,
     "p99": null,
     "max": null
    }
   }
  },
  "HEALTH": {
   "status": "PASS",
   "evidence": {
    "blocked": 0,
    "failed": 0,
    "polls": 20,
    "health_now": "HEALTHY"
   }
  },
  "POLITENESS": {
   "status": "PENDING",
   "evidence": {
    "session_day": null,
    "min_gap_s": null,
    "floor_s": 240.0
   }
  },
  "MAPPING": {
   "status": "PENDING",
   "evidence": {
    "reason": "no reviewed mapping sample (CNBCTV18_NEWS_SITEMAP.json); run `prajna news review-sample --source CNBCTV18_NEWS_SITEMAP` and judge it"
   }
  },
  "TERMS": {
   "status": "PENDING",
   "evidence": {
    "terms": "PENDING"
   }
  },
  "PIT": {
   "status": "PENDING",
   "evidence": {
    "note": "run with --run-tests"
   }
  }
 },
 "summary": {
  "items": 331,
  "live_items": 55,
  "backlog_items": 276,
  "mapping_rate": 0.097,
  "unresolved": 299,
  "stories": {
   "items_with_story": 35,
   "joined_existing": 0,
   "by_method": {
    "FOUNDER": 35
   }
  },
  "assessment": {
   "breaking": 2,
   "impact": {
    "HIGH": 4,
    "UNKNOWN": 17,
    "MEDIUM": 12,
    "LOW": 2
   },
   "scope": {
    "UNKNOWN": 20,
    "SECTOR": 1,
    "STOCK": 6,
    "MACRO": 6,
    "INDEX": 1,
    "MARKET": 1
   }
  },
  "content_fetch_status": {
   "NOT_AVAILABLE": 331
  },
  "rate_limit_events": 0,
  "errors": 0
 }
}
```

### INDIANEXPRESS_BUSINESS_RSS: PENDING

```json
{
 "criteria": {
  "EVIDENCE": {
   "status": "PENDING",
   "evidence": {
    "full_market_sessions": [],
    "polls": 16
   }
  },
  "LATENCY": {
   "status": "PENDING",
   "evidence": {
    "discovery_s": {
     "n": 4,
     "p50": 269.7,
     "p90": 807.4,
     "p95": 920.0,
     "p99": 1010.1,
     "max": 1032.6
    },
    "market_hours": {
     "n": 0,
     "p50": null,
     "p90": null,
     "p95": null,
     "p99": null,
     "max": null
    }
   }
  },
  "HEALTH": {
   "status": "PASS",
   "evidence": {
    "blocked": 0,
    "failed": 0,
    "polls": 16,
    "health_now": "HEALTHY"
   }
  },
  "POLITENESS": {
   "status": "PENDING",
   "evidence": {
    "session_day": null,
    "min_gap_s": null,
    "floor_s": 144.0
   }
  },
  "MAPPING": {
   "status": "PENDING",
   "evidence": {
    "reason": "no reviewed mapping sample (INDIANEXPRESS_BUSINESS_RSS.json); run `prajna news review-sample --source INDIANEXPRESS_BUSINESS_RSS` and judge it"
   }
  },
  "TERMS": {
   "status": "PENDING",
   "evidence": {
    "terms": "PENDING"
   }
  },
  "PIT": {
   "status": "PENDING",
   "evidence": {
    "note": "run with --run-tests"
   }
  }
 },
 "summary": {
  "items": 204,
  "live_items": 4,
  "backlog_items": 200,
  "mapping_rate": 0.034,
  "unresolved": 197,
  "stories": {
   "items_with_story": 4,
   "joined_existing": 0,
   "by_method": {
    "FOUNDER": 4
   }
  },
  "assessment": {
   "breaking": 0,
   "impact": {
    "UNKNOWN": 2,
    "MEDIUM": 2
   },
   "scope": {
    "UNKNOWN": 3,
    "MACRO": 1
   }
  },
  "content_fetch_status": {
   "NOT_AVAILABLE": 204
  },
  "rate_limit_events": 0,
  "errors": 0
 }
}
```

### SEBI_RSS: PENDING

```json
{
 "criteria": {
  "EVIDENCE": {
   "status": "PENDING",
   "evidence": {
    "full_market_sessions": [],
    "polls": 6
   }
  },
  "LATENCY": {
   "status": "NOT_MEASURABLE",
   "evidence": {
    "discovery_s": {
     "n": 0,
     "p50": null,
     "p90": null,
     "p95": null,
     "p99": null,
     "max": null
    },
    "market_hours": {
     "n": 0,
     "p50": null,
     "p90": null,
     "p95": null,
     "p99": null,
     "max": null
    }
   }
  },
  "HEALTH": {
   "status": "PASS",
   "evidence": {
    "blocked": 0,
    "failed": 0,
    "polls": 6,
    "health_now": "HEALTHY"
   }
  },
  "POLITENESS": {
   "status": "PENDING",
   "evidence": {
    "session_day": null,
    "min_gap_s": null,
    "floor_s": 2880.0
   }
  },
  "MAPPING": {
   "status": "PENDING",
   "evidence": {
    "reason": "no reviewed mapping sample (SEBI_RSS.json); run `prajna news review-sample --source SEBI_RSS` and judge it"
   }
  },
  "TERMS": {
   "status": "PENDING",
   "evidence": {
    "terms": "PENDING"
   }
  },
  "PIT": {
   "status": "PENDING",
   "evidence": {
    "note": "run with --run-tests"
   }
  }
 },
 "summary": {
  "items": 50,
  "live_items": 20,
  "backlog_items": 30,
  "mapping_rate": 0.14,
  "unresolved": 43,
  "stories": {
   "items_with_story": 20,
   "joined_existing": 8,
   "by_method": {
    "FOUNDER": 12,
    "SAME_TITLE": 8
   }
  },
  "assessment": {
   "breaking": 0,
   "impact": {
    "MEDIUM": 20
   },
   "scope": {
    "UNKNOWN": 18,
    "STOCK": 2
   }
  },
  "content_fetch_status": {
   "NOT_AVAILABLE": 50
  },
  "rate_limit_events": 0,
  "errors": 0
 }
}
```

## Unsupported

- MONEYCONTROL: HTTP 403 on robots.txt and RSS (bot protection); no bypass
- ZEE_BUSINESS: HTTP 403 on robots.txt and RSS (bot protection); no bypass
- REUTERS: robots.txt Disallow: / for all agents; only a licensed feed would do
