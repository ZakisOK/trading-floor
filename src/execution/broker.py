"""Broker abstraction stub."""
from abc import ABC, abstractmethod


class BaseBroker(ABC):
    """Unified interface over CCXT, Alpaca, and NautilusTrader."""

    @abstractmethod
    async def place_order(
        self, symbol: str, side: str, qty: float, order_type: str
    ) -> dict[str, object]: ...

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool: ...

    @abstractmethod
    async def get_positions(self) -> list[dict[str, object]]: ...
