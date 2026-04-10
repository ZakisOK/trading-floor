from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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

    # Bootstrap Redis Streams consumer groups (idempotent)
    for group_name in CONSUMER_GROUPS.values():
        for stream in _BOOTSTRAP_MAP.get(group_name, []):
            await ensure_consumer_group(stream, group_name)
    logger.info("redis_streams_bootstrapped", groups=len(CONSUMER_GROUPS))

    yield

    logger.info("shutting_down")


app = FastAPI(
    title="The Trading Floor",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "mode": settings.autonomy_mode}
