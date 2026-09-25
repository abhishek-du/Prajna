"""Write authorization.

A CLI flag is not authorization. V1's unauthorized ingestion on 2026-09-15
wrote 269,642 rows because the gate (`EQUITY_INGESTION_AUTHORIZED`) guarded
main() while the library functions underneath it stayed callable — a driver
script imported those directly and bypassed the check entirely.

So the gate lives at the write path, not at the entry point, and it requires
possession of a secret rather than a boolean.
"""

from __future__ import annotations

import hashlib
import hmac

from app.core.config import get_settings
from app.core.errors import AuthorizationError

REDACTED = "<redacted>"


def redact_argv(argv: list[str]) -> list[str]:
    """argv safe to persist: the value of --token (either form) and any
    occurrence of the configured token are replaced. Only the fingerprint
    (authz_token_sha256) identifies the token on a run."""
    configured = get_settings().PRAJNA_WRITE_TOKEN
    out: list[str] = []
    after_flag = False
    for a in argv:
        if after_flag:
            a, after_flag = REDACTED, False
        elif a == "--token":
            after_flag = True
        elif a.startswith("--token="):
            a = "--token=" + REDACTED
        if configured and configured in a:
            a = a.replace(configured, REDACTED)
        out.append(a)
    return out


def token_fingerprint(token: str) -> str:
    """Stable sha256 of a token, safe to persist on ingest_run."""
    return hashlib.sha256(token.encode()).hexdigest()


def authorize_write(supplied: str | None) -> str:
    """Return the fingerprint to stamp on the run, or raise.

    Called by the write path itself, never only by the CLI.
    """
    configured = get_settings().PRAJNA_WRITE_TOKEN
    if not configured:
        raise AuthorizationError(
            "PRAJNA_WRITE_TOKEN is not configured; --commit is refused. "
            "Writes require a configured token, not just the flag."
        )
    if not supplied:
        raise AuthorizationError(
            "--commit requires a write token (--token, or PRAJNA_WRITE_TOKEN in the "
            "environment of the calling process)."
        )
    if not hmac.compare_digest(supplied, configured):
        raise AuthorizationError("write token rejected.")
    return token_fingerprint(configured)
