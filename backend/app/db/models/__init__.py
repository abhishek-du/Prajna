"""All ORM models. Importing this module registers every table on Base.metadata."""

from app.db.base import Base
from app.db.models.canon import CanonCoverage, CanonInstrument
from app.db.models.contracts import (
    Instrument,
    InstrumentAttributeVersion,
    InstrumentLifecyclePeriod,
    InstrumentSecurityClass,
    InstrumentUniverseMembership,
    TradingSession,
)
from app.db.models.control import IngestAnomaly, IngestRun, IngestWatermark, RawPayload
from app.db.models.features import FeatureValue, Stage3Event
from app.db.models.market import (
    GlobalInstrumentContract,
    OhlcvBar,
    OhlcvObservation,
    OhlcvPayloadBasis,
    TickArchive,
)
from app.db.models.preopen import PreopenBook, PreopenSessionStatus, PreopenTick
from app.db.models.reference import (
    CaFactor,
    CorporateAction,
    FundamentalSnapshot,
    MacroObservation,
    NewsArticle,
    NewsInstrument,
)

__all__ = [
    "Base",
    "IngestRun", "RawPayload", "IngestWatermark", "IngestAnomaly",
    "TradingSession", "Instrument", "InstrumentUniverseMembership",
    "InstrumentLifecyclePeriod", "InstrumentAttributeVersion", "InstrumentSecurityClass",
    "PreopenTick", "PreopenBook", "PreopenSessionStatus",
    "OhlcvBar", "TickArchive", "OhlcvPayloadBasis", "OhlcvObservation", "CaFactor",
    "GlobalInstrumentContract",
    "FeatureValue", "Stage3Event",
    "CorporateAction", "FundamentalSnapshot", "MacroObservation", "NewsArticle",
    "NewsInstrument", "CanonInstrument", "CanonCoverage",
]
