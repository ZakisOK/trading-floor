"""Redis Streams producer helpers stub."""
from typing import Any
from src.core.redis import produce
from src.streams import topology


async def emit_market_data(fields: dict[str, Any]) -> str:
    return await produce(topology.MARKET_DATA, fields)


async def emit_signal_raw(fields: dict[str, Any]) -> str:
    return await produce(topology.SIGNALS_RAW, fields)


async def emit_order(fields: dict[str, Any]) -> str:
    return await produce(topology.ORDERS, fields)


async def emit_audit(fields: dict[str, Any]) -> str:
    return await produce(topology.AUDIT, fields, maxlen=0)  # unlimited for audit
