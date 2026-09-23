"""Which instruments the pre-open recorder should watch, and why. PURE.

Two separate decisions, kept separate on purpose:

1. ELIGIBILITY (select_preopen) — an instrument-class rule over the vendor's
   own master: segment + instrument_type, via identity.is_tradeable_equity().
   NEVER the ISIN prefix: 351 tradeable NSE_EQ instruments carry INF ISINs
   (ETFs, incl. NIFTYBEES) and 2 carry IN9. Every instrument that is not
   selected is excluded under a NAMED rule, so any absence is explainable.

2. SUBSCRIPTION (plan_subscription) — a vendor-capacity limit applied to the
   eligible set: validate, de-duplicate, SORT by instrument_key, then cap.
   Sorting first makes the excluded tail identical on every run. The cap is
   configuration, not a fact: Upstox's per-connection limit for `full` mode is
   open blocker B5, and whether several connections could cover more is
   unverified too.

Liquidity is deliberately absent. Filtering by activity belongs to Stage 5
strategy logic; ingestion records what exists.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass

from app.contracts.identity import (
    SEGMENT_NSE_EQ,
    TRADEABLE_EQUITY_SERIES,
    is_tradeable_equity,
    parse_instrument_key,
)

PREOPEN_UNIVERSE = "preopen"
CAP_EXCLUDED_SUFFIX = ".cap_excluded"
PREOPEN_RULES_VERSION = "preopen-v1"

RULE_SELECTED = "selected:tradeable_equity"


def keys_sha256(keys: Iterable[str]) -> str:
    """Content address of an ordered key list. One definition for every list
    this project hashes (universe members, subscribed keys)."""
    return hashlib.sha256("\n".join(keys).encode()).hexdigest()


def rules_fingerprint() -> dict:
    """The rule set as data. Its hash is persisted with every selection, so a
    change to TRADEABLE_EQUITY_SERIES is visible as a different rules_sha256."""
    return {
        "version": PREOPEN_RULES_VERSION,
        "segment": SEGMENT_NSE_EQ,
        "series": sorted(TRADEABLE_EQUITY_SERIES),
        "isin_prefix_rule": None,
    }


def rules_sha256() -> str:
    return hashlib.sha256(
        json.dumps(rules_fingerprint(), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


# ── eligibility ─────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class MasterInstrument:
    """The fields of one Upstox master row that selection and audit need."""

    instrument_key: str
    segment: str
    instrument_type: str | None
    isin: str | None = None
    trading_symbol: str | None = None
    security_type: str | None = None


def classify(inst: MasterInstrument) -> str:
    """The rule that decides this instrument. Exactly one, always named."""
    if inst.segment != SEGMENT_NSE_EQ:
        return f"excluded:segment={inst.segment}"
    if not is_tradeable_equity(inst.segment, inst.instrument_type):
        return f"excluded:series={inst.instrument_type or '<none>'}"
    return RULE_SELECTED


@dataclass(frozen=True, slots=True)
class UniverseSelection:
    members: tuple[str, ...]                        # sorted
    excluded: dict[str, tuple[str, ...]]            # rule -> sorted keys
    series_of: dict[str, str]                       # member key -> series

    @property
    def members_sha256(self) -> str:
        return keys_sha256(self.members)

    def counts(self) -> dict[str, int]:
        out = {RULE_SELECTED: len(self.members)}
        out.update({rule: len(keys) for rule, keys in self.excluded.items()})
        return dict(sorted(out.items()))


def select_preopen(instruments: Iterable[MasterInstrument]) -> UniverseSelection:
    """Deterministic: the same master always yields the same selection, in the
    same order, whatever order its rows arrive in."""
    members: dict[str, str] = {}
    excluded: dict[str, list[str]] = {}
    for inst in instruments:
        rule = classify(inst)
        if rule == RULE_SELECTED:
            members[inst.instrument_key] = (inst.instrument_type or "").upper()
        else:
            excluded.setdefault(rule, []).append(inst.instrument_key)
    ordered = tuple(sorted(members))
    return UniverseSelection(
        members=ordered,
        excluded={r: tuple(sorted(k)) for r, k in sorted(excluded.items())},
        series_of={k: members[k] for k in ordered},
    )


# ── subscription ────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class SubscriptionPlan:
    requested: tuple[str, ...]
    subscribed: tuple[str, ...]
    excluded: tuple[str, ...]
    duplicates: int
    cap: int | None = None

    @property
    def keys_sha256(self) -> str:
        return keys_sha256(self.subscribed)


def plan_subscription(keys: Iterable[str], cap: int | None) -> SubscriptionPlan:
    """Validate, de-duplicate, SORT, then cap. Excluded keys are returned by
    name, never summarised as a count. `cap=None` means no cap."""
    if cap is not None and cap < 1:
        raise ValueError(f"cap must be >= 1 or None, got {cap}")
    raw = [k.strip() for k in keys if k and k.strip()]
    for k in raw:
        parse_instrument_key(k)  # raises on malformed
    uniq = sorted(set(raw))
    if cap is not None and len(uniq) > cap:
        kept, dropped = uniq[:cap], uniq[cap:]
    else:
        kept, dropped = uniq, []
    return SubscriptionPlan(tuple(uniq), tuple(kept), tuple(dropped), len(raw) - len(uniq), cap)


# ── sharding across connections ─────────────────────────────────────────────
# Measured live 2026-09-23 (docs/2026-09-23_M1_LIVE_SMOKE.md): Upstox serves at
# most 2,000 keys per connection in `full` mode and ignores the rest silently;
# two concurrent connections were both fully served. Beyond two is UNVERIFIED.
MEASURED_KEYS_PER_CONNECTION = 2000
MEASURED_CONCURRENT_CONNECTIONS = 2


@dataclass(frozen=True, slots=True)
class ShardPlan:
    """Keys assigned to connections: disjoint, contiguous in sorted order, and
    identical on every run for the same universe."""

    requested: tuple[str, ...]
    shards: tuple[tuple[str, ...], ...]
    excluded: tuple[str, ...]          # beyond total capacity, by name
    duplicates: int
    per_connection: int
    max_connections: int

    @property
    def subscribed(self) -> tuple[str, ...]:
        return tuple(k for s in self.shards for k in s)

    @property
    def universe_sha256(self) -> str:
        return keys_sha256(self.requested)

    def shard_plan(self, i: int) -> SubscriptionPlan:
        """Shard i as a single-connection plan (no further cap)."""
        return SubscriptionPlan(self.shards[i], self.shards[i], (), 0, self.per_connection)


def plan_shards(keys: Iterable[str], *, per_connection: int, max_connections: int) -> ShardPlan:
    if per_connection < 1 or max_connections < 1:
        raise ValueError("per_connection and max_connections must be >= 1")
    base = plan_subscription(keys, per_connection * max_connections)
    kept = base.subscribed
    shards = tuple(kept[i : i + per_connection] for i in range(0, len(kept), per_connection))
    return ShardPlan(base.requested, shards, base.excluded, base.duplicates,
                     per_connection, max_connections)
