"""Upstox vendor errors."""

from app.core.errors import VendorAuthError, VendorError

__all__ = ["VendorError", "VendorAuthError", "UpstoxLoginStepError"]


class UpstoxLoginStepError(VendorAuthError):
    """A named step of the TOTP login flow failed.

    Carries the step so a failure says WHICH of the six stages broke, rather
    than a generic 'login failed'.
    """

    def __init__(self, step: str, detail: str):
        self.step = step
        super().__init__(f"[{step}] {detail}")
