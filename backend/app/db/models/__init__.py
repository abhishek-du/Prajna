"""All ORM models. Importing this module registers every table on Base.metadata."""

from app.db.base import Base
from app.db.models.contracts import Instrument, InstrumentUniverseMembership, TradingSession
from app.db.models.control import IngestAnomaly, IngestRun, IngestWatermark, RawPayload
from app.db.models.market import OhlcvBar, TickArchive
from app.db.models.preopen import PreopenBook, PreopenSessionStatus, PreopenTick
from app.db.models.reference import (
    CorporateAction, FundamentalSnapshot, MacroObservation, NewsArticle,
)

__all__ = [
    "Base",
    "IngestRun", "RawPayload", "IngestWatermark", "IngestAnomaly",
    "TradingSession", "Instrument", "InstrumentUniverseMembership",
    "PreopenTick", "PreopenBook", "PreopenSessionStatus",
    "OhlcvBar", "TickArchive",
    "CorporateAction", "FundamentalSnapshot", "MacroObservation", "NewsArticle",
]
