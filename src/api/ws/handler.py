"""WebSocket broadcast handler — fans out Redis Streams events to browser clients."""
import asyncio
import contextlib
import json
from typing import Any

import structlog
from fastapi import WebSocket, WebSocketDisconnect

from src.core.redis import get_redis
from src.data.feeds.ingestor import ohlcv_to_ws_message
from src.streams.topology import AGENT_RESULTS, ALERTS, MARKET_DATA, PNL, SIGNALS_RAW, TRADES, AUDIT

logger = structlog.get_logger()

# Streams the broadcast consumer subscribes to
_BROADCAST_STREAMS: list[str] = [MARKET_DATA, PNL, ALERTS, AGENT_RESULTS, SIGNALS_RAW, TRADES, AUDIT]
_BROADCAST_GROUP = "cg:ws_broadcast"


class ConnectionManager:
    """Manages active WebSocket connections and broadcasts messages to all."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections.append(ws)
        logger.info("ws_client_connected", total=len(self._connections))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            if ws in self._connections:
                self._connections.remove(ws)
        logger.info("ws_client_disconnected", total=len(self._connections))

    async def broadcast(self, data: dict[str, Any]) -> None:
        if not self._connections:
            return
        message = json.dumps(data)
        dead: list[WebSocket] = []
        async with self._lock:
            connections = list(self._connections)
        for ws in connections:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(ws)


manager = ConnectionManager()


async def websocket_endpoint(ws: WebSocket) -> None:
    """FastAPI WebSocket endpoint. Clients receive all broadcast events."""
    await manager.connect(ws)
    try:
        # Keep alive — receive any client messages (ping/subscriptions)
        while True:
            data = await ws.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await ws.send_text(json.dumps({"type": "pong"}))
            except (json.JSONDecodeError, AttributeError):
                pass
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(ws)


async def broadcast_loop() -> None:
    """Background task: reads Redis Streams and broadcasts to all WebSocket clients.

    Runs as a FastAPI lifespan background task.
    """
    r = get_redis()
    consumer_name = "ws-broadcast-0"

    # Ensure consumer groups exist for all broadcast streams
    for stream in _BROADCAST_STREAMS:
        with contextlib.suppress(Exception):
            await r.xgroup_create(stream, _BROADCAST_GROUP, id="0", mkstream=True)

    while True:
        try:
            results: list[Any] = await r.xreadgroup(
                _BROADCAST_GROUP,
                consumer_name,
                {stream: ">" for stream in _BROADCAST_STREAMS},
                count=20,
                block=500,
            )
            for stream_name, messages in results or []:
                for msg_id, fields in messages:
                    msg = _fields_to_broadcast(stream_name, fields)
                    if msg:
                        await manager.broadcast(msg)
                    await r.xack(stream_name, _BROADCAST_GROUP, msg_id)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("broadcast_loop_error", error=str(e))
            await asyncio.sleep(1)


def _fields_to_broadcast(stream: str, fields: dict[str, Any]) -> dict[str, Any] | None:
    """Convert stream fields to a typed WebSocket message."""
    from datetime import UTC, datetime
    ts = datetime.now(UTC).isoformat()
    if stream == MARKET_DATA:
        return ohlcv_to_ws_message(fields)
    if stream == ALERTS:
        return {"type": "alert", "ts": ts, "stream": stream, "level": "warning",
                "msg": fields.get("message") or fields.get("msg") or "alert", **fields}
    if stream == PNL:
        return {"type": "pnl", "ts": ts, "stream": stream, "level": "info",
                "msg": f"{fields.get('symbol','?')} closed {fields.get('reason','')} pnl={fields.get('pnl','?')}", **fields}
    if stream == AGENT_RESULTS:
        return {"type": "agent_result", "ts": ts, "stream": stream, "level": "info",
                "msg": fields.get("message") or "agent_result", **fields}
    if stream == SIGNALS_RAW:
        agent = fields.get("agent_name") or fields.get("agent_id") or "?"
        sym = fields.get("symbol", "?")
        direction = fields.get("direction", "?")
        conf = fields.get("confidence", "?")
        return {"type": "signal", "ts": ts, "stream": stream, "level": "info",
                "msg": f"{agent} \u2192 {direction} {sym} @ {conf}", **fields}
    if stream == TRADES:
        return {"type": "trade", "ts": ts, "stream": stream, "level": "info",
                "msg": f"{fields.get('side','?')} {fields.get('symbol','?')} @ {fields.get('filled_price','?')}", **fields}
    if stream == AUDIT:
        return {"type": "audit", "ts": ts, "stream": stream, "level": "debug",
                "msg": fields.get("event") or fields.get("action") or "audit", **fields}
    return None
