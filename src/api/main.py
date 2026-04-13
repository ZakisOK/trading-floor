import asyncio
import contextlib
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from src.api.routers.market import router as market_router
from src.api.routers.backtest import router as backtest_router
from src.api.routers.agents import router as agents_router
from src.api.routers.orders import router as orders_router
from src.api.routers.briefing import router as briefing_router
from src.api.routers.execution import router as execution_router
from src.api.settings import router as settings_router
from src.api.ws.handler import broadcast_loop, websocket_endpoint
from src.core.config import settings
from src.core.redis import ensure_consumer_group
from src.streams.topology import CONSUMER_GROUPS

logger = structlog.get_logger()

# fmt: off
_BOOTSTRAP_MAP: dict[str, list[str]] = {
    "cg:market_analysts": ["stream:market_data", "stream:agent:tasks"],
    "cg:risk_managers":   ["stream:signals:raw"],
    "cg:executors":       ["stream:signals:validated"],
    "cg:portfolio":       ["stream:signals:validated", "stream:trades", "stream:agent:results"],
    "cg:ws_broadcast":    [
        "stream:market_data", "stream:orders", "stream:pnl",
        "stream:alerts", "stream:agent:results",
    ],
    "cg:audit_writer":    ["stream:trades", "stream:pnl", "stream:audit"],
}
# fmt: on


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("starting_up", environment=settings.environment)
    for group_name in CONSUMER_GROUPS.values():
        for stream in _BOOTSTRAP_MAP.get(group_name, []):
            await ensure_consumer_group(stream, group_name)
    logger.info("redis_streams_bootstrapped", groups=len(CONSUMER_GROUPS))
    broadcast_task = asyncio.create_task(broadcast_loop())
    logger.info("broadcast_loop_started")
    yield
    broadcast_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await broadcast_task
    logger.info("shutting_down")


app = FastAPI(title="The Trading Floor", version="0.8.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(market_router)
app.include_router(backtest_router)
app.include_router(agents_router)
app.include_router(orders_router)
app.include_router(briefing_router)
app.include_router(execution_router)
app.include_router(settings_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "mode": settings.autonomy_mode}


@app.websocket("/ws")
async def ws_route(websocket: WebSocket) -> None:
    await websocket_endpoint(websocket)
