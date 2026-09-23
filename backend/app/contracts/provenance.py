"""Provenance primitives: payload hashing and the run lifecycle contract.

Constraint #7: every persisted record carries source, run_id, payload_sha256,
fetched_at and knowable_at. No silent provenance gaps.

Hashing rule: the hash covers the vendor's bytes ONLY. Our wall clock is
excluded, so the same vendor response always hashes identically and re-ingestion
is naturally idempotent. (Ported from V1's defensive/evidence_store.py, which
got this right.)
"""

from __future__ import annotations

import enum
import hashlib
import json


class RunStatus(str, enum.Enum):
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    ABORTED = "ABORTED"


class RunMode(str, enum.Enum):
    DRY_RUN = "DRY_RUN"
    COMMIT = "COMMIT"


class AnomalySeverity(str, enum.Enum):
    WARN = "WARN"
    FAIL = "FAIL"


class AnomalyKind(str, enum.Enum):
    COVERAGE_DROP = "COVERAGE_DROP"
    COVERAGE_CAP = "COVERAGE_CAP"
    SCHEMA_DRIFT = "SCHEMA_DRIFT"
    STALE_VENDOR_TS = "STALE_VENDOR_TS"
    PARSE_REJECT = "PARSE_REJECT"
    GAP = "GAP"
    DUPLICATE_KEY = "DUPLICATE_KEY"
    VENDOR_ERROR = "VENDOR_ERROR"
    # Vendor clock ahead of ours: knowable_at is bounded by fetched_at instead.
    CLOCK_SKEW = "CLOCK_SKEW"
    # A frame's vendor time falls on a different IST date than the session.
    SESSION_MISMATCH = "SESSION_MISMATCH"


# Source identifiers. Upstox-only by constraint #1; there is deliberately no
# ZERODHA/KITE/YFINANCE member and a test asserts that stays true.
class Source(str, enum.Enum):
    UPSTOX_WS_V3 = "UPSTOX_WS_V3"
    UPSTOX_REST_V2 = "UPSTOX_REST_V2"
    UPSTOX_REST_V3 = "UPSTOX_REST_V3"
    UPSTOX_ASSETS = "UPSTOX_ASSETS"


def payload_sha256(data: bytes) -> str:
    """Content address of a vendor payload. Vendor bytes only."""
    return hashlib.sha256(data).hexdigest()


def config_sha256(mapping: dict) -> str:
    """Stable hash of a config/request mapping.

    sort_keys=True is not cosmetic: V1's calendar artifact was invalidated by a
    hash computed over unsorted JSON that was then re-serialised differently
    (see its rca_report.md).
    """
    return hashlib.sha256(
        json.dumps(mapping, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
