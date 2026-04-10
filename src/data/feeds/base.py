"""Base market data feed interface."""
from abc import ABC, abstractmethod
from collections.abc import Callable, Coroutine
from typing import Any

from src.data.schemas.market import OHLCVSchema

OnBarCallback = Callable[[OHLCVSchema], Coroutine[Any, Any, None]]


class BaseFeed(ABC):
    """Abstract base for all market data feed adapters.

    Feeds are responsible for:
    - Connecting to the data source (WebSocket or REST)
    - Subscribing to symbols
    - Calling on_bar(ohlcv) for each completed candle
    - Publishing to stream:market_data via the producer
    """

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the data source."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Close the connection gracefully."""
        ...

    @abstractmethod
    async def subscribe(self, symbols: list[str]) -> None:
        """Subscribe to additional symbols."""
        ...

    @abstractmethod
    async def stream(self, on_bar: OnBarCallback) -> None:
        """Start streaming OHLCV data. Calls on_bar for each new candle. Blocks until stopped."""
        ...
