"""Market data Pydantic schemas stub."""
from pydantic import BaseModel, ConfigDict


class OHLCVSchema(BaseModel):
    model_config = ConfigDict(strict=True)

    symbol: str
    timeframe: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    # TODO: Add timestamp field (Phase 1)
