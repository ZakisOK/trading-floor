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
from src.api.routers.signals import router as signals_router
from src.api.routers.llm import router as llm_router
from src.api.routers.commodities import router as commodities_router
from src.api.routers.desks import router as desks_router
from src.api.routers.narrative import router as narrative_router
from src.api.settings import router as settings_router
from src.agents.registry import log_roster
from src.api.ws.handler import broadcast_loop, websocket_endpoint
from src.core.config import settings
from src.core.redis import ensure_consumer_group
from src.streams.topology import CONSUMER_GROUPS, EPISODES, TRADE_OUTCOMES

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
    "cg:episode_writer":  [EPISODES],         # Week 1 / B4 — drains into agent_episodes
    "cg:outcome_writer":  [TRADE_OUTCOMES],   # Week 2 / B2 — drains into trade_outcomes + agent_contributions
}
# fmt: on


async def _probe_active_venue() -> None:
    """Refuse to start if the active venue's broker can't be reached.

    sim → always passes. alpaca_paper / live → must answer get_account().
    """
    from src.core.security import activate_kill_switch
    from src.execution.broker import get_alpaca_broker, get_execution_venue

    venue = await get_execution_venue()
    if venue == "sim":
        logger.info("broker_probe_skipped", reason="sim venue")
        return

    paper_flag = venue != "live"
    broker = get_alpaca_broker(paper=paper_flag)
    if broker is None:
        await activate_kill_switch(
            reason=f"startup_probe: alpaca client unavailable (venue={venue})",
            operator_id="startup_probe",
        )
        raise RuntimeError(
            f"Refusing to start: venue={venue} requires Alpaca and the client "
            f"is unavailable (credentials missing or SDK not installed). "
            f"Kill switch activated. Set config:system.execution_venue=sim to "
            f"recover the API for diagnostics."
        )
    try:
        account = await broker.get_account()
    except Exception as exc:
        await activate_kill_switch(
            reason=f"startup_probe: get_account raised {exc}",
            operator_id="startup_probe",
        )
        raise RuntimeError(
            f"Refusing to start: venue={venue} probe failed: {exc}. "
            f"Kill switch activated."
        ) from exc
    if not account:
        await activate_kill_switch(
            reason=f"startup_probe: get_account returned empty (venue={venue})",
            operator_id="startup_probe",
        )
        raise RuntimeError(
            f"Refusing to start: venue={venue} get_account returned empty. "
            f"Kill switch activated."
        )
    logger.info(
        "broker_probe_ok",
        venue=venue,
        account_status=account.get("status"),
        paper=paper_flag,
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("starting_up", environment=settings.environment)

    # Week 1 / B2: every agent must have a non-null, well-formed agent_version
    # before we accept traffic. Failure here is fatal — a missing version means
    # episodes from that agent would fail the CHECK constraint downstream.
    log_roster()

    # Week 1 / A3: if the active venue is Alpaca, probe connectivity before
    # accepting orders. Failure trips the kill switch (loud + structural) and
    # raises so systemd restarts us — the caller can flip venue to sim from
    # Redis if they need the API up for diagnostic work.
    await _probe_active_venue()

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


@app.middleware("http")
async def no_cache_api(request, call_next):  # type: ignore[no-untyped-def]
    """Force browsers + any intermediary to always re-fetch API responses."""
    response = await call_next(request)
    if request.url.path.startswith("/api") or request.url.path == "/health":
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

app.include_router(market_router)
app.include_router(backtest_router)
app.include_router(agents_router)
app.include_router(orders_router)
app.include_router(briefing_router)
app.include_router(execution_router)
app.include_router(signals_router)
app.include_router(llm_router)
app.include_router(commodities_router)
app.include_router(desks_router)
app.include_router(narrative_router)
app.include_router(settings_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "mode": settings.autonomy_mode}


@app.get("/api/health/broker")
async def health_broker() -> dict[str, object]:
    """Per-venue broker connectivity (Week 1 / A3).

    Reports whether the active venue's broker is currently reachable. The
    intent is human + monitor consumption; the order path itself uses
    structured exceptions, not this endpoint.
    """
    from src.execution.broker import get_alpaca_broker, get_execution_venue

    venue = await get_execution_venue()
    payload: dict[str, object] = {"venue": venue}
    if venue == "sim":
        payload["broker_available"] = True
        payload["detail"] = "sim venue — local PaperBroker always available"
        return payload

    paper_flag = venue != "live"
    broker = get_alpaca_broker(paper=paper_flag)
    if broker is None:
        payload["broker_available"] = False
        payload["detail"] = "alpaca client unavailable (credentials missing or SDK not installed)"
        return payload
    try:
        account = await broker.get_account()
    except Exception as exc:  # noqa: BLE001
        payload["broker_available"] = False
        payload["detail"] = f"alpaca get_account raised: {exc}"
        return payload
    payload["broker_available"] = bool(account)
    payload["account_status"] = account.get("status") if isinstance(account, dict) else None
    payload["paper"] = paper_flag
    return payload


@app.websocket("/ws")
async def ws_route(websocket: WebSocket) -> None:
    await websocket_endpoint(websocket)


@app.websocket("/ws/stream")
async def ws_stream_route(websocket: WebSocket) -> None:
    await websocket_endpoint(websocket)
