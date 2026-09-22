"""Constraint #1, enforced by the suite rather than by good intentions.

V2 is Upstox-only. These tests make a Zerodha/Kite/yfinance dependency a build
failure instead of something discovered months later in a forensic audit.
"""

from __future__ import annotations

import pathlib
import re

APP = pathlib.Path(__file__).resolve().parents[2] / "app"
PY = sorted(APP.rglob("*.py"))

# Matches imports and attribute access, not prose in a docstring or comment.
BANNED_CODE = re.compile(
    r"^\s*(?:from|import)\s+\S*(?:kiteconnect|yfinance|zerodha)"
    r"|(?<![\w.])(?:KiteConnect|KiteTicker|yf\.Ticker)(?![\w])",
    re.IGNORECASE | re.MULTILINE,
)


def _strip_comments_and_docstrings(src: str) -> str:
    import io
    import tokenize
    out = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            out.append(tok.string)
    except Exception:
        return src
    return "\n".join(out)


def test_no_banned_vendor_imports():
    offenders = []
    for p in PY:
        code = _strip_comments_and_docstrings(p.read_text())
        if BANNED_CODE.search(code):
            offenders.append(str(p.relative_to(APP)))
    assert not offenders, f"banned vendor usage in: {offenders}"


def test_no_vendor_modules_other_than_upstox():
    vendor = APP / "vendor"
    subs = {p.name for p in vendor.iterdir() if p.is_dir() and not p.name.startswith("__")}
    assert subs <= {"upstox"}, f"unexpected vendor packages: {subs - {'upstox'}}"


def test_source_enum_is_upstox_only():
    from app.contracts.provenance import Source
    assert all(s.value.startswith("UPSTOX_") for s in Source)


def test_no_kite_instrument_token_columns():
    """Constraint #4: no Kite instrument-token fields anywhere in the schema."""
    from app.db.models import Base
    bad = [
        f"{t}.{c.name}"
        for t, tbl in Base.metadata.tables.items()
        for c in tbl.columns
        if re.search(r"kite|instrument_token", c.name, re.IGNORECASE)
    ]
    assert not bad, f"Kite-flavoured columns present: {bad}"


def test_parsers_are_pure():
    """parsers/ must not import IO. This is what makes offline replay possible."""
    banned = re.compile(r"^\s*(?:from|import)\s+(httpx|websockets|sqlalchemy|asyncpg|requests)"
                        r"|^\s*from\s+app\.(storage|db)\b", re.MULTILINE)
    offenders = [
        str(p.name) for p in (APP / "parsers").rglob("*.py")
        if banned.search(_strip_comments_and_docstrings(p.read_text()))
    ]
    assert not offenders, f"parsers importing IO: {offenders}"
