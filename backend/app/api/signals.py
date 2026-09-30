"""Signals endpoint (Stage 3 UI contract only; no simulated or fake signals)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.schemas import Envelope, Meta, SignalsResponse
from app.core.clock import now

router = APIRouter(prefix="/signals", tags=["signals"])


@router.get("", response_model=Envelope[SignalsResponse])
async def get_signals() -> Envelope[SignalsResponse]:
    now_utc = now()
    # Strict compliance: Stage 3 is locked, do not generate fake signals.
    resp = SignalsResponse()
    return Envelope(
        data=resp,
        meta=Meta(
            as_of=now_utc,
            generated_at=now_utc,
            point_in_time=True,
            notes=["Stage 3 remains locked in production. Signal contracts defined."],
        ),
    )
