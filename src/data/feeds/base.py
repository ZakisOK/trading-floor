"""Base market data feed stub."""
from abc import ABC, abstractmethod


class BaseFeed(ABC):
    """Abstract base for all market data feed adapters."""

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def subscribe(self, symbols: list[str]) -> None: ...
