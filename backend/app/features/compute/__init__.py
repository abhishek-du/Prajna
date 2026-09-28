"""Pure feature computations: no database, no network, no clock.

Every function returns Result = (value, reason). Exactly one of the two is
None: a value is always finite; a missing value always says why. Nothing is
ever filled, interpolated or defaulted.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

OK = None
MISSING_INPUT = "MISSING_INPUT"                # a required input does not exist (yet)
INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"  # fewer usable observations than the window
MALFORMED_INPUT = "MALFORMED_INPUT"            # a vendor payload did not have the expected shape
NOT_APPLICABLE = "NOT_APPLICABLE"              # e.g. a pre-open feature at PRE_SESSION
DIVISION_UNDEFINED = "DIVISION_UNDEFINED"      # a zero / non-positive denominator
UNSUPPORTED = "UNSUPPORTED"                    # no data source exists (registry)
UNKNOWN = "UNKNOWN"                            # no definition exists (registry)
REASONS = (MISSING_INPUT, INSUFFICIENT_HISTORY, MALFORMED_INPUT, NOT_APPLICABLE,
           DIVISION_UNDEFINED, UNSUPPORTED, UNKNOWN)

Result = tuple[float | None, str | None]


def ok(x: float) -> Result:
    """A finite value, normalised to 12 significant digits (determinism across reruns)."""
    if x is None or not math.isfinite(x):
        return (None, DIVISION_UNDEFINED)
    return (float(f"{x:.12g}"), None)


def miss(reason: str) -> Result:
    assert reason in REASONS, reason
    return (None, reason)


@dataclass(frozen=True, slots=True)
class Bar:
    """One daily bar as used by features (already point-in-time and basis-checked)."""
    day: date
    open: float
    high: float
    low: float
    close: float
    volume: float
