"""Typed errors. Every one of these is a FAIL-LOUD signal.

V1's dominant failure mode was silence: an expired Celery task logged nothing,
a contract violation dropped 1,083 symbols' daily bars without an alert, and a
blanket `except Exception` in the news loop swallowed a NameError every 15
seconds for weeks. Nothing in V2 may fail quietly.
"""


class PrajnaError(Exception):
    """Base for everything this application raises deliberately."""


class ConfigError(PrajnaError):
    """Configuration is missing, malformed, or forbidden."""


class DatabaseIsolationError(ConfigError):
    """The configured DSN points at a database V2 must never touch.

    This is a hard stop at import time, not a runtime warning. V1's research
    harness wrote synthetic rows into the live trade-authorization table
    because nothing structurally prevented it.
    """


class AuthorizationError(PrajnaError):
    """A write was attempted without a valid authorization token."""


class VendorError(PrajnaError):
    """The vendor returned something we could not use."""


class VendorAuthError(VendorError):
    """Vendor credentials are absent, expired, or rejected."""


class SchemaDriftError(VendorError):
    """The vendor payload no longer matches the contract we pinned.

    Raised rather than silently ignored: an unrecognised field may be the one
    carrying the value a strategy depends on.
    """


class ContractViolation(PrajnaError):
    """A row violated an invariant (session, identity, timeframe, knowable_at)."""


class KnowableAtUnverified(ContractViolation):
    """knowable_at cannot be derived from evidence for this data type.

    Never resolved by inventing a value. Callers fall back to the conservative
    bound (fetched_at) and flag the row knowable_at_verified = False.
    """


class IngestCheckFailed(PrajnaError):
    """A pre-write gate (coverage / freshness / row-delta) rejected the run."""


class RateLimited(VendorError):
    """The vendor signalled a rate limit (HTTP 429 or a rate-limit error body).

    Never retried. Upstox documents "temporary suspension of access" for
    breaches, so the only safe response is to stop the job with its checkpoint
    intact and resume later.
    """
