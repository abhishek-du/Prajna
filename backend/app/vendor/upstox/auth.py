"""Upstox access-token acquisition and validity.

TWO THINGS V1 CONFLATED, SEPARATED HERE:

  credentials present  != token valid

V1's `settings.upstox_authenticated` only checked that a token STRING was
non-empty, so an expired token read as healthy and the integration went dark
for a large part of every day with nothing raised. Upstox tokens expire daily
(~03:30 IST). Here, `ensure_access_token()` PROBES the token against
/v2/user/profile and mints a new one when the probe fails.

The token is cached in var/ (gitignored, 0600), NOT written back into .env.
V1 rewrote its own .env via `set_key` on every refresh, which means its
configuration file mutated underneath a running process that had already read
it.

THE LOGIN FLOW — six steps, reimplemented from V1's proven curl_cffi
implementation (crawler/upstox_totp/). Endpoints and payload shapes are taken
from there because they are verified to work; the structure is V2's own.

  1 GET  api.upstox.com/v2/login/authorization/dialog   -> user_id, client_id
  2 POST service.upstox.com/login/open/v6/auth/1fa/otp/generate      -> otp token
  3 POST service.upstox.com/login/open/v4/auth/1fa/otp-totp/verify   (TOTP)
  4 POST service.upstox.com/login/open/v3/auth/2fa                   (PIN, base64)
  5 POST service.upstox.com/login/v2/oauth/authorize                 -> auth code
  6 POST api.upstox.com/v2/login/authorization/token                 -> access token
"""

from __future__ import annotations

import base64
import datetime as _dt
import json
import pathlib
import random
import string
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

import pyotp
from curl_cffi import requests as curl

from app.core.clock import IST, now
from app.core.config import BACKEND_ROOT, get_settings
from app.core.logging import get_logger
from app.vendor.upstox.errors import UpstoxLoginStepError, VendorAuthError

log = get_logger("upstox.auth")

API = "https://api.upstox.com"
SERVICE = "https://service.upstox.com"
LOGIN = "https://login.upstox.com"
# Upstox's own internal redirect target for steps 4 and 5. Distinct from the
# app's registered redirect_uri, which is used in steps 1 and 6.
UPSTOX_INTERNAL_REDIRECT = "https://api-v2.upstox.com/login/authorization/redirect"

TOKEN_PATH = BACKEND_ROOT / "var" / "upstox_token.json"
PROBE_TIMEOUT = 15
STEP_TIMEOUT = 30


@dataclass(frozen=True, slots=True)
class TokenRecord:
    access_token: str
    minted_at: _dt.datetime
    user_id: str | None = None
    email: str | None = None

    def to_json(self) -> str:
        return json.dumps({
            "access_token": self.access_token,
            "minted_at": self.minted_at.isoformat(),
            "user_id": self.user_id,
            "email": self.email,
        }, indent=2)

    @staticmethod
    def from_json(raw: str) -> TokenRecord:
        d = json.loads(raw)
        return TokenRecord(
            access_token=d["access_token"],
            minted_at=_dt.datetime.fromisoformat(d["minted_at"]),
            user_id=d.get("user_id"),
            email=d.get("email"),
        )


# ── cache ───────────────────────────────────────────────────────────────────
def load_cached() -> TokenRecord | None:
    if not TOKEN_PATH.exists():
        return None
    try:
        return TokenRecord.from_json(TOKEN_PATH.read_text())
    except Exception:
        return None


def save_cached(rec: TokenRecord) -> None:
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(rec.to_json())
    TOKEN_PATH.chmod(0o600)


# ── validity probe ──────────────────────────────────────────────────────────
def probe(access_token: str) -> tuple[bool, dict]:
    """Ask Upstox whether the token works. The only honest validity check."""
    r = curl.get(
        f"{API}/v2/user/profile",
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        timeout=PROBE_TIMEOUT,
        impersonate="chrome131",
    )
    if r.status_code == 200:
        return True, r.json().get("data", {})
    try:
        return False, r.json()
    except Exception:
        return False, {"status_code": r.status_code}


# ── login ───────────────────────────────────────────────────────────────────
def _request_id() -> str:
    return "WPRO-" + "".join(random.choices(string.ascii_letters + string.digits, k=10))


def _browser_headers(rid: str) -> dict[str, str]:
    ua = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")
    return {
        "accept": "*/*",
        "accept-language": "en-GB,en;q=0.9",
        "content-type": "application/json",
        "origin": LOGIN,
        "referer": LOGIN,
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
        "user-agent": ua,
        "x-device-details": (
            "platform=WEB|osName=Mac OS/10.15.7|osVersion=Chrome/140.0.0.0|"
            "appVersion=4.0.0|modelName=Chrome|manufacturer=Apple|"
            f"uuid=3Z1IVTlV4rUUGbNp8KP0|userAgent=Upstox 3.0 {ua}"
        ),
        "x-request-id": rid,
    }


def _ok(r, step: str) -> dict:
    try:
        body = r.json()
    except Exception:
        raise UpstoxLoginStepError(step, f"HTTP {r.status_code}, non-JSON body") from None
    if r.status_code >= 400 or body.get("status") == "error":
        errs = body.get("errors") or body.get("error") or body
        raise UpstoxLoginStepError(step, f"HTTP {r.status_code}: {json.dumps(errs)[:300]}")
    return body


def mint_token(*, verify_tls: bool = True) -> TokenRecord:
    """Execute the six-step TOTP login. Performs a REAL login to a live account."""
    s = get_settings()
    s.require("UPSTOX_API_KEY", "UPSTOX_API_SECRET", "UPSTOX_REDIRECT_URL",
              "UPSTOX_USERNAME", "UPSTOX_PIN", "UPSTOX_TOTP_SECRET")

    rid = _request_id()
    sess = curl.Session(impersonate="chrome131", headers=_browser_headers(rid),
                        verify=verify_tls)
    try:
        # 1 — authorization dialog; the redirect carries user_id / client_id.
        r = sess.get(f"{API}/v2/login/authorization/dialog",
                     params={"response_type": "code", "client_id": s.UPSTOX_API_KEY,
                             "redirect_uri": s.UPSTOX_REDIRECT_URL},
                     allow_redirects=True, timeout=STEP_TIMEOUT)
        q = parse_qs(urlparse(r.url).query)
        if not (q.get("user_id") and q.get("client_id")):
            raise UpstoxLoginStepError(
                "1-dialog", f"redirect lacked user_id/client_id; params={list(q)}")
        user_id, client_id = q["user_id"][0], q["client_id"][0]
        log.info("upstox.login.step", step="1-dialog", ok=True)

        # 2 — request the OTP challenge token.
        body = _ok(sess.post(f"{SERVICE}/login/open/v6/auth/1fa/otp/generate",
                             json={"data": {"mobileNumber": s.UPSTOX_USERNAME,
                                            "userId": user_id}},
                             timeout=STEP_TIMEOUT), "2-otp-generate")
        otp_token = (body.get("data") or {}).get("validateOTPToken")
        if not otp_token:
            raise UpstoxLoginStepError("2-otp-generate", "no validateOTPToken in response")
        log.info("upstox.login.step", step="2-otp-generate", ok=True)

        # 3 — answer it with the current TOTP.
        _ok(sess.post(f"{SERVICE}/login/open/v4/auth/1fa/otp-totp/verify",
                      json={"data": {"otp": pyotp.TOTP(s.UPSTOX_TOTP_SECRET).now(),
                                     "validateOtpToken": otp_token}},
                      timeout=STEP_TIMEOUT), "3-totp-verify")
        log.info("upstox.login.step", step="3-totp-verify", ok=True)

        # 4 — second factor: the PIN, base64-encoded.
        pin_b64 = base64.b64encode(s.UPSTOX_PIN.encode()).decode()
        _ok(sess.post(f"{SERVICE}/login/open/v3/auth/2fa",
                      params={"client_id": client_id,
                              "redirect_uri": UPSTOX_INTERNAL_REDIRECT},
                      json={"data": {"twoFAMethod": "SECRET_PIN", "inputText": pin_b64}},
                      allow_redirects=True, timeout=STEP_TIMEOUT), "4-pin")
        log.info("upstox.login.step", step="4-pin", ok=True)

        # 5 — approve the OAuth grant; the response carries the auth code.
        body = _ok(sess.post(f"{SERVICE}/login/v2/oauth/authorize",
                             params={"client_id": client_id,
                                     "redirect_uri": UPSTOX_INTERNAL_REDIRECT,
                                     "requestId": rid, "response_type": "code"},
                             json={"data": {"userOAuthApproval": True}},
                             allow_redirects=True, timeout=STEP_TIMEOUT), "5-oauth")
        redirect_uri = (body.get("data") or {}).get("redirectUri", "")
        code = parse_qs(urlparse(redirect_uri).query).get("code", [None])[0]
        if not code:
            raise UpstoxLoginStepError("5-oauth", f"no code in redirectUri {redirect_uri[:120]}")
        log.info("upstox.login.step", step="5-oauth", ok=True)

        # 6 — exchange the code. Fresh session: the login cookies must not be
        # sent to the token endpoint.
        r = curl.post(
            f"{API}/v2/login/authorization/token",
            data={"code": code, "client_id": s.UPSTOX_API_KEY,
                  "client_secret": s.UPSTOX_API_SECRET,
                  "redirect_uri": s.UPSTOX_REDIRECT_URL,
                  "grant_type": "authorization_code"},
            headers={"accept": "application/json",
                     "content-type": "application/x-www-form-urlencoded"},
            timeout=STEP_TIMEOUT, impersonate="chrome131", verify=verify_tls,
        )
        body = _ok(r, "6-token")
        token = body.get("access_token")
        if not token:
            raise UpstoxLoginStepError("6-token", f"no access_token; keys={list(body)}")
        log.info("upstox.login.step", step="6-token", ok=True)

        return TokenRecord(access_token=token, minted_at=now(),
                           user_id=body.get("user_id"), email=body.get("email"))
    finally:
        sess.close()


def ensure_access_token(*, force: bool = False, verify_tls: bool = True) -> TokenRecord:
    """Return a token that has been PROVEN to work, minting one if needed."""
    if not force:
        cached = load_cached()
        if cached:
            ok, _ = probe(cached.access_token)
            if ok:
                log.info("upstox.token.cached_valid",
                         age_hours=round((now() - cached.minted_at).total_seconds() / 3600, 2))
                return cached
            log.info("upstox.token.cached_invalid", action="minting a new token")

    rec = mint_token(verify_tls=verify_tls)
    ok, profile = probe(rec.access_token)
    if not ok:
        raise VendorAuthError(f"freshly minted token failed its own probe: {profile}")
    rec = TokenRecord(rec.access_token, rec.minted_at,
                      profile.get("user_id") or rec.user_id,
                      profile.get("email") or rec.email)
    save_cached(rec)
    log.info("upstox.token.minted", user_id=rec.user_id,
             expires_hint="Upstox tokens expire daily ~03:30 IST")
    return rec


def token_status() -> dict:
    """Human-readable status. Never returns the token itself."""
    rec = load_cached()
    if not rec:
        return {"cached": False, "valid": False, "reason": "no cached token"}
    ok, detail = probe(rec.access_token)
    return {
        "cached": True,
        "valid": ok,
        "minted_at_ist": rec.minted_at.astimezone(IST).isoformat(timespec="seconds"),
        "age_hours": round((now() - rec.minted_at).total_seconds() / 3600, 2),
        "user_id": rec.user_id,
        "detail": None if ok else detail,
    }
