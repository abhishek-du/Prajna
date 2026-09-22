"""Pre-write gates. Every one of them fails LOUD.

V1's contract enforcement dropped rows and logged. The measurable result: 1,083
symbols (28.7% of its universe) stopped receiving daily bars on 2026-08-27 and
nobody noticed for 25 days, because a drop was a log line rather than an event.

Here a gate breach writes an ingest_anomaly row and, at FAIL severity, aborts
the run before anything is committed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.contracts.provenance import AnomalyKind, AnomalySeverity
from app.core.errors import IngestCheckFailed


@dataclass(slots=True)
class Anomaly:
    severity: AnomalySeverity
    kind: AnomalyKind
    subject: str | None
    detail: dict


@dataclass(slots=True)
class CheckResult:
    anomalies: list[Anomaly] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return any(a.severity is AnomalySeverity.FAIL for a in self.anomalies)

    def add(self, severity, kind, subject=None, **detail) -> None:
        self.anomalies.append(Anomaly(severity, kind, subject, detail))

    def raise_if_failed(self) -> None:
        if self.failed:
            fails = [a for a in self.anomalies if a.severity is AnomalySeverity.FAIL]
            raise IngestCheckFailed(
                f"{len(fails)} blocking anomaly(ies): "
                + "; ".join(f"{a.kind.value}:{a.subject}" for a in fails)
            )


def check_coverage(
    result: CheckResult,
    *,
    observed: int,
    baseline: int | None,
    stream: str,
    min_ratio: float = 0.80,
) -> None:
    """Row count against the trailing baseline.

    A sudden collapse in coverage is the signature of the V1 failure above: the
    pipeline kept running and reported success while producing a fraction of
    the rows it used to.
    """
    if baseline is None or baseline == 0:
        return
    ratio = observed / baseline
    if ratio < min_ratio:
        result.add(
            AnomalySeverity.FAIL, AnomalyKind.COVERAGE_DROP, stream,
            observed=observed, baseline=baseline, ratio=round(ratio, 4),
            min_ratio=min_ratio,
        )


def check_universe_cap(
    result: CheckResult, *, requested: list[str], cap: int, stream: str
) -> list[str]:
    """Apply a vendor subscription cap, naming every symbol it excludes.

    Upstox's `full` mode admits 2,000 instrument keys per subscription. When the
    eligible universe exceeds that, the excluded keys are ENUMERATED in the
    anomaly detail — never summarised as a count, never silent.
    """
    if len(requested) <= cap:
        return requested
    kept, dropped = requested[:cap], requested[cap:]
    result.add(
        AnomalySeverity.WARN, AnomalyKind.COVERAGE_CAP, stream,
        requested=len(requested), cap=cap, dropped_count=len(dropped),
        dropped_keys=dropped,
    )
    return kept


def check_schema_drift(
    result: CheckResult, *, unknown_fields: set[str], stream: str
) -> None:
    """An unrecognised vendor field fails the run.

    It may be the one carrying the value a strategy needs. Ignoring it silently
    is how a pipeline keeps "succeeding" while losing information.
    """
    if unknown_fields:
        result.add(
            AnomalySeverity.FAIL, AnomalyKind.SCHEMA_DRIFT, stream,
            unknown_fields=sorted(unknown_fields),
        )


def check_vendor_freshness(
    result: CheckResult, *, vendor_ts, now_ts, stream: str, max_age_seconds: int
) -> None:
    """Stale vendor data must never be consumed as if it were fresh.

    V1's FII/DII crawler returned the PREVIOUS day's row on failure, logged
    'DATA STALE', and returned it anyway; nothing downstream had a freshness
    gate.
    """
    age = (now_ts - vendor_ts).total_seconds()
    if age > max_age_seconds:
        result.add(
            AnomalySeverity.FAIL, AnomalyKind.STALE_VENDOR_TS, stream,
            vendor_ts=vendor_ts.isoformat(), age_seconds=round(age, 1),
            max_age_seconds=max_age_seconds,
        )


def check_provenance_complete(result: CheckResult, *, rows: list[dict], stream: str) -> None:
    """No row may reach the database without full provenance (constraint #7)."""
    required = ("source", "run_id", "payload_sha256", "fetched_at", "knowable_at")
    bad = [
        i for i, r in enumerate(rows)
        if any(r.get(k) in (None, "") for k in required)
    ]
    if bad:
        result.add(
            AnomalySeverity.FAIL, AnomalyKind.PARSE_REJECT, stream,
            rows_missing_provenance=len(bad), first_indices=bad[:20],
        )
