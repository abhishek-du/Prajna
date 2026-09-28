# Multi-source news acceptance

**Generated:** 2026-09-28T11:41:55.048792+00:00 by `prajna acceptance news` (read-only; regenerate, do not edit).

## Overall: **NOT PASSED**

a PASS unlocks nothing by itself: writes also need the per-source flag, terms APPROVED, Stage 2 PASS and a token.

| Source | Status | EVIDENCE | LATENCY | HEALTH | POLITENESS | MAPPING | TERMS | PIT |
|---|---|---|---|---|---|---|---|---|
| NSE_ANNOUNCEMENTS | **PENDING** | PENDING | PASS | PASS | PENDING | PENDING | PENDING | PASS |
| ET_STOCKS_RSS | **PENDING** | PENDING | PENDING | PASS | PENDING | PENDING | PENDING | PASS |
| BS_MARKETS_RSS | **PENDING** | PENDING | PASS | PASS | PENDING | PENDING | PENDING | PASS |
| BL_MARKETS_RSS | **PENDING** | PENDING | PASS | PASS | PENDING | PENDING | PENDING | PASS |
| MINT_MARKETS_RSS | **PENDING** | PENDING | PENDING | PASS | PENDING | PENDING | PENDING | PASS |
| CNBCTV18_NEWS_SITEMAP | **PENDING** | PENDING | PASS | PASS | PENDING | PENDING | PENDING | PASS |
| INDIANEXPRESS_BUSINESS_RSS | **PENDING** | PENDING | PENDING | PASS | PENDING | PENDING | PENDING | PASS |
| SEBI_RSS | **PENDING** | PENDING | NOT_MEASURABLE | PASS | PENDING | PENDING | PENDING | PASS |

## Per source

### NSE_ANNOUNCEMENTS: PENDING

```json
{
 "criteria": {
  "EVIDENCE": {
   "status": "PENDING",
   "evidence": {
    "full_market_sessions": [],
    "polls": 9
   }
  },
  "LATENCY": {
   "status": "PASS",
   "evidence": {
    "discovery_s": {
     "n": 461,
     "p50": 416.1,
     "p90": 855.0,
     "p95": 1078.3,
     "p99": 1221.7,
     "max": 1301.3
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
    "failed": 1,
    "polls": 9,
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
   "status": "PASS",
   "evidence": {
    "exit": 0,
    "summary": "149 passed in 7.04s"
   }
  }
 },
 "summary": {
  "items": 1691,
  "live_items": 463,
  "backlog_items": 1228,
  "mapping_rate": 0.823,
  "unresolved": 300,
  "stories": {
   "items_with_story": 82,
   "joined_existing": 23,
   "by_method": {
    "FOUNDER": 59,
    "SAME_TITLE": 23
   }
  },
  "assessment": {
   "breaking": 1,
   "impact": {
    "LOW": 66,
    "MEDIUM": 14,
    "UNKNOWN": 1,
    "HIGH": 1
   },
   "scope": {
    "STOCK": 80,
    "UNKNOWN": 2
   }
  },
  "content_fetch_status": {
   "NOT_AVAILABLE": 1691
  },
  "rate_limit_events": 0,
  "errors": 1
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
    "polls": 9
   }
  },
  "LATENCY": {
   "status": "PENDING",
   "evidence": {
    "discovery_s": {
     "n": 2,
     "p50": 1178.3,
     "p90": 1194.0,
     "p95": 1195.9,
     "p99": 1197.5,
     "max": 1197.9
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
    "polls": 9,
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
   "status": "PASS",
   "evidence": {
    "exit": 0,
    "summary": "149 passed in 7.04s"
   }
  }
 },
 "summary": {
  "items": 52,
  "live_items": 2,
  "backlog_items": 50,
  "mapping_rate": 0.442,
  "unresolved": 29,
  "stories": {
   "items_with_story": 0,
   "joined_existing": 0,
   "by_method": {}
  },
  "assessment": {
   "breaking": 0,
   "impact": {},
   "scope": {}
  },
  "content_fetch_status": {
   "NOT_AVAILABLE": 52
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
    "polls": 7
   }
  },
  "LATENCY": {
   "status": "PASS",
   "evidence": {
    "discovery_s": {
     "n": 6,
     "p50": 711.3,
     "p90": 851.3,
     "p95": 853.3,
     "p99": 854.9,
     "max": 855.3
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
    "polls": 7,
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
   "status": "PASS",
   "evidence": {
    "exit": 0,
    "summary": "149 passed in 7.04s"
   }
  }
 },
 "summary": {
  "items": 41,
  "live_items": 6,
  "backlog_items": 35,
  "mapping_rate": 0.341,
  "unresolved": 27,
  "stories": {
   "items_with_story": 1,
   "joined_existing": 0,
   "by_method": {
    "FOUNDER": 1
   }
  },
  "assessment": {
   "breaking": 0,
   "impact": {
    "UNKNOWN": 1
   },
   "scope": {
    "MACRO": 1
   }
  },
  "content_fetch_status": {
   "NOT_AVAILABLE": 41
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
    "polls": 5
   }
  },
  "LATENCY": {
   "status": "PASS",
   "evidence": {
    "discovery_s": {
     "n": 7,
     "p50": 598.9,
     "p90": 1036.3,
     "p95": 1224.1,
     "p99": 1374.2,
     "max": 1411.8
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
    "polls": 5,
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
   "status": "PASS",
   "evidence": {
    "exit": 0,
    "summary": "149 passed in 7.04s"
   }
  }
 },
 "summary": {
  "items": 67,
  "live_items": 7,
  "backlog_items": 60,
  "mapping_rate": 0.104,
  "unresolved": 60,
  "stories": {
   "items_with_story": 4,
   "joined_existing": 0,
   "by_method": {
    "FOUNDER": 4
   }
  },
  "assessment": {
   "breaking": 2,
   "impact": {
    "HIGH": 2,
    "MEDIUM": 1,
    "UNKNOWN": 1
   },
   "scope": {
    "UNKNOWN": 2,
    "SECTOR": 1,
    "MACRO": 1
   }
  },
  "content_fetch_status": {
   "NOT_AVAILABLE": 67
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
    "polls": 8
   }
  },
  "LATENCY": {
   "status": "PENDING",
   "evidence": {
    "discovery_s": {
     "n": 4,
     "p50": 255.6,
     "p90": 747.1,
     "p95": 823.2,
     "p99": 884.0,
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
   "status": "PASS",
   "evidence": {
    "exit": 0,
    "summary": "149 passed in 7.04s"
   }
  }
 },
 "summary": {
  "items": 39,
  "live_items": 4,
  "backlog_items": 35,
  "mapping_rate": 0.282,
  "unresolved": 28,
  "stories": {
   "items_with_story": 0,
   "joined_existing": 0,
   "by_method": {}
  },
  "assessment": {
   "breaking": 0,
   "impact": {},
   "scope": {}
  },
  "content_fetch_status": {
   "NOT_AVAILABLE": 39
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
    "polls": 8
   }
  },
  "LATENCY": {
   "status": "PASS",
   "evidence": {
    "discovery_s": {
     "n": 24,
     "p50": 816.4,
     "p90": 1278.3,
     "p95": 1341.6,
     "p99": 1446.3,
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
    "polls": 8,
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
   "status": "PASS",
   "evidence": {
    "exit": 0,
    "summary": "149 passed in 7.04s"
   }
  }
 },
 "summary": {
  "items": 300,
  "live_items": 24,
  "backlog_items": 276,
  "mapping_rate": 0.087,
  "unresolved": 274,
  "stories": {
   "items_with_story": 4,
   "joined_existing": 0,
   "by_method": {
    "FOUNDER": 4
   }
  },
  "assessment": {
   "breaking": 1,
   "impact": {
    "HIGH": 1,
    "UNKNOWN": 3
   },
   "scope": {
    "UNKNOWN": 4
   }
  },
  "content_fetch_status": {
   "NOT_AVAILABLE": 300
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
    "polls": 4
   }
  },
  "LATENCY": {
   "status": "PENDING",
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
    "polls": 4,
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
   "status": "PASS",
   "evidence": {
    "exit": 0,
    "summary": "149 passed in 7.04s"
   }
  }
 },
 "summary": {
  "items": 200,
  "live_items": 0,
  "backlog_items": 200,
  "mapping_rate": 0.035,
  "unresolved": 193,
  "stories": {
   "items_with_story": 0,
   "joined_existing": 0,
   "by_method": {}
  },
  "assessment": {
   "breaking": 0,
   "impact": {},
   "scope": {}
  },
  "content_fetch_status": {
   "NOT_AVAILABLE": 200
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
    "polls": 3
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
    "polls": 3,
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
   "status": "PASS",
   "evidence": {
    "exit": 0,
    "summary": "149 passed in 7.04s"
   }
  }
 },
 "summary": {
  "items": 30,
  "live_items": 0,
  "backlog_items": 30,
  "mapping_rate": 0.167,
  "unresolved": 25,
  "stories": {
   "items_with_story": 0,
   "joined_existing": 0,
   "by_method": {}
  },
  "assessment": {
   "breaking": 0,
   "impact": {},
   "scope": {}
  },
  "content_fetch_status": {
   "NOT_AVAILABLE": 30
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
