"""Stage 2.1 connectors: one classifying fetch contract over the approved
vendor clients. Upstox is the only approved vendor (constraint #1); NSE data
reaches Prajna through Upstox (pre-open WebSocket, market info), so there is
deliberately no NSE HTTP connector and no crawler."""

from app.connectors.base import Connector, FetchOutcome, FetchResult
from app.connectors.upstox import UpstoxConnector

__all__ = ["Connector", "FetchOutcome", "FetchResult", "UpstoxConnector"]
