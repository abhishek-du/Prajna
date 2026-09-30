"""Portfolio & execution endpoint (Stage 4/5 UI contract only; no simulated or live orders)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.schemas import Envelope, Meta, PortfolioResponse
from app.core.clock import now

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("", response_model=Envelope[PortfolioResponse])
async def get_portfolio() -> Envelope[PortfolioResponse]:
    now_utc = now()
    # Strict compliance: Order routing and broker execution disabled.
    resp = PortfolioResponse()
    return Envelope(
        data=resp,
        meta=Meta(
            as_of=now_utc,
            generated_at=now_utc,
            point_in_time=True,
            notes=["Stage 4/5 order execution is locked. Read-only compliance state."],
        ),
    )
