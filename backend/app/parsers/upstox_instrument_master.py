"""Upstox instrument master (NSE.json.gz) -> MasterInstrument rows. PURE.

The vendor publishes a gzipped JSON array of objects (verified 2026-09-22,
80,127 rows), with `segment`, `instrument_type` (the NSE series for NSE_EQ),
`instrument_key`, `isin`, `trading_symbol` and more.

No row disappears silently. A row this parser cannot use is reported as an
Issue under an explicit rule, with its position in the file:

  excluded:malformed_row          not an object / no usable instrument_key or segment
  excluded:key_segment_mismatch   instrument_key prefix disagrees with `segment`
  duplicate (identical)           WARN; one copy kept
  duplicate (conflicting)         FAIL; identity is ambiguous, nothing is guessed
"""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass, field
from typing import Any

from app.contracts.identity import parse_instrument_key
from app.contracts.provenance import AnomalyKind, AnomalySeverity
from app.contracts.universe import MasterInstrument

GZIP_MAGIC = b"\x1f\x8b"
RULE_MALFORMED = "excluded:malformed_row"
RULE_KEY_SEGMENT = "excluded:key_segment_mismatch"


class MasterDecodeError(Exception):
    """The payload is not a JSON array. The archived bytes stay re-parseable."""


@dataclass(frozen=True, slots=True)
class Issue:
    severity: AnomalySeverity
    kind: AnomalyKind
    subject: str | None
    detail: dict[str, Any]


@dataclass(slots=True)
class ParsedMaster:
    row_count: int = 0
    instruments: list[MasterInstrument] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    # rule -> row indices (malformed rows may have no key to name them by)
    rejected: dict[str, list[int]] = field(default_factory=dict)

    def reject(self, rule: str, index: int, **detail: Any) -> None:
        self.rejected.setdefault(rule, []).append(index)
        self.issues.append(Issue(AnomalySeverity.WARN, AnomalyKind.PARSE_REJECT, rule,
                                 {"row_index": index, **detail}))


def _str(v: Any) -> str | None:
    return v.strip() if isinstance(v, str) and v.strip() else None


def decode(data: bytes) -> list:
    raw = gzip.decompress(data) if data[:2] == GZIP_MAGIC else data
    try:
        doc = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as e:
        raise MasterDecodeError(f"instrument master is not JSON: {e}") from None
    if not isinstance(doc, list):
        raise MasterDecodeError(f"instrument master is a {type(doc).__name__}, not a list")
    return doc


def parse_master(data: bytes) -> ParsedMaster:
    rows = decode(data)
    out = ParsedMaster(row_count=len(rows))
    by_key: dict[str, tuple[int, MasterInstrument]] = {}

    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            out.reject(RULE_MALFORMED, i, reason=f"row is a {type(row).__name__}")
            continue
        key, seg = _str(row.get("instrument_key")), _str(row.get("segment"))
        if not key or not seg:
            out.reject(RULE_MALFORMED, i, reason="missing instrument_key or segment",
                       instrument_key=row.get("instrument_key"), segment=row.get("segment"))
            continue
        try:
            parsed = parse_instrument_key(key)
        except ValueError:
            out.reject(RULE_MALFORMED, i, reason="unparseable instrument_key", instrument_key=key)
            continue
        if parsed.segment != seg:
            out.reject(RULE_KEY_SEGMENT, i, instrument_key=key, segment=seg)
            continue

        inst = MasterInstrument(
            instrument_key=key, segment=seg,
            instrument_type=_str(row.get("instrument_type")),
            isin=_str(row.get("isin")),
            trading_symbol=_str(row.get("trading_symbol")),
            security_type=_str(row.get("security_type")),
        )
        if key in by_key:
            first_i, first = by_key[key]
            if first == inst:
                out.issues.append(Issue(AnomalySeverity.WARN, AnomalyKind.DUPLICATE_KEY, key,
                                        {"row_index": i, "first_row_index": first_i,
                                         "identical": True}))
            else:
                out.issues.append(Issue(AnomalySeverity.FAIL, AnomalyKind.DUPLICATE_KEY, key,
                                        {"row_index": i, "first_row_index": first_i,
                                         "identical": False, "first": first.__repr__(),
                                         "second": inst.__repr__()}))
            continue
        by_key[key] = (i, inst)

    out.instruments = [inst for _, inst in by_key.values()]
    return out
