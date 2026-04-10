"""Market data Pydantic schemas."""
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class OHLCVSchema(BaseModel):
    model_config = ConfigDict(strict=True)

    symbol: str
    exchange: str
    timeframe: str
    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


class OHLCVResponse(BaseModel):
    model_config = ConfigDict(strict=False)

    symbol: str
    exchange: str
    timeframe: str
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class MarketDataMessage(BaseModel):
    """WebSocket message for real-time market data."""

    model_config = ConfigDict(strict=False)

    type: str = "ohlcv"
    symbol: str
    exchange: str
    timeframe: str
    ts: str  # ISO format for JSON compatibility
    open: float
    high: float
    low: float
    close: float
    volume: float


class SymbolInfo(BaseModel):
    model_config = ConfigDict(strict=True)

    symbol: str
    exchange: str
    asset_class: str = Field(description="crypto | equity | options")
    base: str = ""
    quote: str = ""
