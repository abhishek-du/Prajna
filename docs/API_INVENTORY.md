# Prajna AI Trading System — Backend API Inventory

**System**: Prajna AI Trading System (AutoTrade Pro V2)  
**Version**: 2.0.0-PROD  
**Base URL**: `http://localhost:8000/api/v1`  
**WebSocket URL**: `ws://localhost:8000/ws/live`  
**Document**: `docs/API_INVENTORY.md`  

---

## 1. Global Response Envelope Specification

All REST endpoints wrap response payloads in a typed, standardized envelope with execution metadata, provenance timestamps, and strict UTC serialization:

```json
{
  "data": { ... },
  "meta": {
    "version": "v2",
    "timestamp": "2026-09-25T13:30:00.123456Z",
    "server_time_ist": "19:00:00 IST",
    "stage_status": "STAGE_1_STAGE_2_OBSERVATION"
  }
}
```

---

## 2. Complete REST Endpoint Inventory

| Endpoint Path | Method | Purpose | Query / Path Parameters | Underlying Database Tables / Views |
|---|---|---|---|---|
| `/overview` | `GET` | Macro overview dashboard: NIFTY 50, BANK NIFTY, INDIA VIX, GIFT NIFTY, market status, news, pipeline freshness | None | `ohlcv_bar`, `canon_market_bar`, `trading_session`, `news_article`, `app_run` |
| `/instruments` | `GET` | Search and filter the NSE active universe with pagination | `q` (string), `sector` (string), `security_class` (string), `segment` (string), `status` (string, default `ACTIVE`), `limit` (int, 1-200), `offset` (int) | `instrument`, `canon_instrument`, `instrument_security_class` |
| `/instruments/{key}` | `GET` | Deep SCD2 metadata, ISIN, trading symbol, tick size, security class for a single instrument | `key` (path, string, e.g. `NSE_INDEX\|Nifty 50` or `NSE_EQ\|INE002A01018`) | `instrument`, `canon_instrument`, `instrument_security_class` |
| `/candles/{key}` | `GET` | Multi-timeframe OHLCV candles with optional Point-in-Time corporate action adjustment | `key` (path), `timeframe` (`1m`, `15m`, `1h`, `1d`), `adjusted` (bool), `from_date` (date), `to_date` (date), `limit` (int, max 2000) | `ohlcv_bar`, `pit.bars_adjusted`, `canon_market_bar` |
| `/technicals/{key}` | `GET` | Real point-in-time OHLCV metrics; Stage 3 indicators strictly locked | `key` (path), `timeframe` (`1m`, `15m`, `1h`, `1d`) | `ohlcv_bar` |
| `/fundamentals/{key}` | `GET` | Corporate financials: key valuation ratios (P/E, P/B, ROE, ROCE, EPS), financial statements, and verified corporate action history | `key` (path) | `instrument`, `fundamental_snapshot`, `corporate_action`, `ca_factor` |
| `/global-markets` | `GET` | 13 macro benchmarks (N225, USDINR, S&P 500, etc.) enforcing P5 Global Finality | None | `canon_market_bar` (filters: `finality in ('CONFIRMED', 'CONFIRMED_BY_AGE')`) |
| `/news` | `GET` | News intelligence stream with provenance timestamps (`published_at`, `received_at`, `processed_at`) | `instrument_key` (string), `limit` (int, 1-100) | `news_article`, `news_instrument` |
| `/screener` | `GET` | Multi-factor universe screener with disabled Stage 3/4/5 placeholder columns | `sector` (string), `min_price` (float), `max_price` (float), `min_pe` (float), `max_pe` (float), `limit` (int), `offset` (int) | `instrument`, `canon_instrument`, `instrument_security_class`, `ohlcv_bar`, `fundamental_snapshot` |
| `/signals` | `GET` | UI contract for future trading signals; returns explicit STAGE_3_LOCKED status | None | No model queries (returns empty array with locked compliance banner) |
| `/portfolio` | `GET` | UI contract for holdings, positions, and orders; returns STAGE_4_5_LOCKED status | None | No live broker execution (compliance observation mode) |
| `/health` | `GET` | Complete subsystem diagnostics: DB, token fingerprint, close status, instrument master, global refresh, B2 timing contract, backups, acceptance matrix | None | `pg_stat_database`, `app_run`, `token_record`, `instrument`, `canon_market_bar`, `news_article` |
| `/ops/runs` | `GET` | Ingestion runs audit ledger | `status` (string), `stream` (string), `limit` (int) | `app_run` |
| `/ops/anomalies` | `GET` | Automated data quality anomaly detection records | `severity` (string), `limit` (int) | `anomaly` |
| `/ops/revisions` | `GET` | Corporate action factors and price basis revision ledger | `timeframe` (string), `limit` (int) | `data_revision`, `ca_factor` |
| `/ops/backups` | `GET` | List of verified database backup snapshots with SHA256 checksums | None | File system inspection: `var/archive/backup_*.pg_dump` |
| `/ops/warmup` | `GET` | Interactive Stage 3 historical feature warm-up planning calculator | `sessions` (int, default 20), `timeframes` (string), `fraction` (float, default 0.25) | `trading_session`, `instrument` |

---

## 3. Detailed Request & Response Schemas

### 3.1 `GET /api/v1/candles/{key}`
Returns OHLCV candles. Supports Point-in-Time (PIT) adjustment via the `adjusted=true` parameter.

**Request**:
```http
GET /api/v1/candles/NSE_INDEX|Nifty%2050?timeframe=1d&limit=100&adjusted=false HTTP/1.1
Host: localhost:8000
```

**Response**:
```json
{
  "data": {
    "instrument_key": "NSE_INDEX|Nifty 50",
    "timeframe": "1d",
    "adjusted": false,
    "total": 100,
    "candles": [
      {
        "timestamp_utc": "2026-09-24T10:00:00Z",
        "timestamp_ist": "2026-09-24T15:30:00+05:30",
        "open": 25800.5,
        "high": 25950.0,
        "low": 25750.2,
        "close": 25890.1,
        "volume": 35210040.0,
        "knowable_at": "2026-09-24T10:00:00Z"
      }
    ]
  },
  "meta": {
    "version": "v2",
    "timestamp": "2026-09-25T13:30:00Z"
  }
}
```

### 3.2 `GET /api/v1/global-markets`
Enforces the P5 Global Finality Contract. Bars marked `REVISED`, `PLACEHOLDER`, or `UNCONFIRMED` are strictly withheld from the payload.

**Response**:
```json
{
  "data": {
    "markets": [
      {
        "instrument_key": "GLOBAL|N225",
        "trading_symbol": "Nikkei 225",
        "name": "Japan Nikkei 225",
        "segment": "GLOBAL_INDEX",
        "label_date": "2026-09-25",
        "open": 37800.0,
        "high": 38100.5,
        "low": 37650.0,
        "close": 37950.2,
        "volume": null,
        "finality": "CONFIRMED",
        "knowable_at": "2026-09-25T06:30:00Z",
        "confirmed_at": "2026-09-25T12:30:00Z",
        "weekend_label_share": 0.0,
        "semantics": "CALENDAR_DATE",
        "confirm_hours": 6
      }
    ],
    "withheld_counts": {
      "REVISED": 2,
      "PLACEHOLDER": 0,
      "UNCONFIRMED": 1
    }
  },
  "meta": { ... }
}
```

### 3.3 `GET /api/v1/health`
Exposes subsystem health and diagnostics without ever revealing write tokens or broker credentials.

**Response**:
```json
{
  "data": {
    "overall_status": "HEALTHY",
    "database": {
      "name": "database",
      "status": "PASS",
      "details": {
        "engine": "postgresql+asyncpg",
        "target_database": "prajna",
        "v1_isolation_enforced": true
      }
    },
    "token_auth": {
      "name": "token_auth",
      "status": "PASS",
      "details": {
        "token_available": true,
        "fingerprint": "eyJ...4a89",
        "minted_at": "2026-09-25T03:00:00Z",
        "age_hours": 10.5
      }
    },
    "timing_contract": {
      "name": "timing_contract",
      "status": "WARNING",
      "details": {
        "rule_status": "FALSIFIED_EMPIRICALLY_MEASURED",
        "1m_max_observed_seconds": 95.6,
        "15m_max_observed_seconds": 110.9,
        "1h_max_observed_seconds": 111.0,
        "recommended_rules": {
          "1m": "120s (25% safety margin)",
          "15m": "180s (62% safety margin)",
          "1h": "180s (62% safety margin)"
        }
      }
    },
    "acceptance_summary": {
      "stage_1_status": "PROCEEDING",
      "stage_2_baseline": "14/16 PASS",
      "stage_3_status": "LOCKED"
    }
  },
  "meta": { ... }
}
```

---

## 4. Error Handling Standards

| HTTP Status Code | Meaning | Example Scenario |
|---|---|---|
| `400 Bad Request` | Unsupported query parameters | Querying an unsupported timeframe (e.g. `2m`, `3h`) or asking for negative sessions |
| `404 Not Found` | Entity not present in database | Querying an unknown instrument key or an instrument without bars |
| `500 Internal Error` | Database connection error | Temporary database unavailability or unexpected internal query failure |
