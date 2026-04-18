"""Settings API router — read/write system config stored in Redis.

Endpoints:
  GET  /api/settings              — full config snapshot (API keys masked)
  POST /api/settings              — bulk-update config fields
  POST /api/settings/exchange/test — test ccxt connection, return latency
  POST /api/settings/toggle-live  — flip paper_trading flag (requires confirmation)
"""
from __future__ import annotations

import time
from typing import Any

import ccxt.async_support as ccxt_async
import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.core.redis import get_redis

router = APIRouter(prefix="/api/settings", tags=["settings"])
logger = structlog.get_logger()

_EXCHANGE_IDS = ("binance", "coinbase", "kraken", "polymarket")
_EXCHANGE_CRED_FIELDS = ("api_key", "secret", "passphrase", "sandbox", "enabled")
_SYSTEM_FIELDS = (
    "paper_trading",
    "max_daily_loss_pct",
    "max_position_size_pct",
    "trailing_stop_pct",
    "kill_switch_enabled",
    "autonomy_mode",
)
_AGENT_NAMES = (
    "atlas", "bear", "bull", "carry_agent", "commodities_analyst",
    "copy_trade_scout", "cot_analyst", "diana", "eia_analyst",
    "macro_analyst", "marcus", "momentum_agent", "nova",
    "options_flow_agent", "polymarket_scout", "rex", "sage",
    "scout", "sentiment_analyst", "vera", "xrp_analyst",
)
_ASSET_SYMBOLS = (
    # Crypto Tier 1
    "BTC/USDT", "ETH/USDT", "XRP/USDT", "SOL/USDT",
    # Crypto Alts
    "BNB/USDT", "ADA/USDT", "AVAX/USDT", "DOGE/USDT",
    "LINK/USDT", "DOT/USDT", "MATIC/USDT", "UNI/USDT",
    # Commodity Futures
    "GC=F", "CL=F", "SI=F", "HG=F", "NG=F", "ZW=F", "ZC=F", "ZS=F",
)


# ── helpers ────────────────────────────────────────────────────────────────

def _mask(value: str | None) -> str:
    """Return last 4 chars visible, rest replaced with *."""
    if not value:
        return ""
    if len(value) <= 4:
        return "*" * len(value)
    return "*" * (len(value) - 4) + value[-4:]


def _is_key_field(field_name: str) -> bool:
    return field_name in ("api_key", "secret", "passphrase")


# ── GET /api/settings ──────────────────────────────────────────────────────

@router.get("")
async def get_settings() -> dict[str, Any]:
    """Return complete config snapshot. Sensitive fields are masked."""
    redis = get_redis()

    # System config
    system_raw: dict[str, str] = await redis.hgetall("config:system") or {}
    system: dict[str, Any] = {
        "paper_trading": system_raw.get("paper_trading", "true"),
        "max_daily_loss_pct": float(system_raw.get("max_daily_loss_pct", "2.0")),
        "max_position_size_pct": float(system_raw.get("max_position_size_pct", "5.0")),
        "trailing_stop_pct": float(system_raw.get("trailing_stop_pct", "5.0")),
        "kill_switch_enabled": system_raw.get("kill_switch_enabled", "false"),
    }

    # Exchange configs (keys masked)
    exchanges: dict[str, Any] = {}
    for ex_id in _EXCHANGE_IDS:
        raw: dict[str, str] = await redis.hgetall(f"config:exchange:{ex_id}") or {}
        exchanges[ex_id] = {
            "api_key": _mask(raw.get("api_key")),
            "secret": _mask(raw.get("secret")),
            "passphrase": _mask(raw.get("passphrase")),
            "sandbox": raw.get("sandbox", "true"),
            "enabled": raw.get("enabled", "false"),
        }

    # Agent configs
    agents: dict[str, Any] = {}
    for name in _AGENT_NAMES:
        raw_a: dict[str, str] = await redis.hgetall(f"config:agent:{name}") or {}
        agents[name] = {
            "enabled": raw_a.get("enabled", "true"),
            "confidence_threshold": float(raw_a.get("confidence_threshold", "0.65")),
        }

    # Asset universe
    enabled_assets_raw = await redis.smembers("config:assets:enabled")
    enabled_assets = enabled_assets_raw if enabled_assets_raw else set(_ASSET_SYMBOLS)

    # Notifications
    notif_raw: dict[str, str] = await redis.hgetall("config:notifications") or {}
    notifications: dict[str, str] = {"webhook_url": notif_raw.get("webhook_url", "")}

    return {
        "system": system,
        "exchanges": exchanges,
        "agents": agents,
        "assets": {"enabled": list(enabled_assets), "all": list(_ASSET_SYMBOLS)},
        "notifications": notifications,
    }


# ── POST /api/settings ─────────────────────────────────────────────────────

class SettingsUpdate(BaseModel):
    system: dict[str, Any] | None = None
    exchanges: dict[str, dict[str, Any]] | None = None
    agents: dict[str, dict[str, Any]] | None = None
    assets: dict[str, Any] | None = None
    notifications: dict[str, str] | None = None


@router.post("")
async def update_settings(body: SettingsUpdate) -> dict[str, str]:
    """Write config fields to Redis. Raw API keys overwrite masked values only
    when the submitted value is non-empty and does not start with '*'."""
    redis = get_redis()

    if body.system:
        allowed = {k: str(v) for k, v in body.system.items() if k in _SYSTEM_FIELDS}
        if allowed:
            await redis.hset("config:system", mapping=allowed)

    if body.exchanges:
        for ex_id, fields in body.exchanges.items():
            if ex_id not in _EXCHANGE_IDS:
                continue
            to_write: dict[str, str] = {}
            for field_name in _EXCHANGE_CRED_FIELDS:
                val = str(fields.get(field_name, ""))
                # Skip masked placeholders (user didn't change the field)
                if _is_key_field(field_name) and val.startswith("*"):
                    continue
                if val:
                    to_write[field_name] = val
            if to_write:
                await redis.hset(f"config:exchange:{ex_id}", mapping=to_write)

    if body.agents:
        for name, cfg in body.agents.items():
            if name not in _AGENT_NAMES:
                continue
            agent_data: dict[str, str] = {}
            if "enabled" in cfg:
                agent_data["enabled"] = str(cfg["enabled"]).lower()
            if "confidence_threshold" in cfg:
                agent_data["confidence_threshold"] = str(cfg["confidence_threshold"])
            if agent_data:
                await redis.hset(f"config:agent:{name}", mapping=agent_data)

    if body.assets and "enabled" in body.assets:
        symbols: list[str] = [s for s in body.assets["enabled"] if s in _ASSET_SYMBOLS]
        await redis.delete("config:assets:enabled")
        if symbols:
            await redis.sadd("config:assets:enabled", *symbols)

    if body.notifications:
        notif_data = {k: str(v) for k, v in body.notifications.items()}
        if notif_data:
            await redis.hset("config:notifications", mapping=notif_data)

    logger.info("settings_updated")
    return {"status": "ok"}


# ── POST /api/settings/exchange/test ──────────────────────────────────────

class ExchangeTestRequest(BaseModel):
    exchange_id: str


@router.post("/exchange/test")
async def test_exchange_connection(body: ExchangeTestRequest) -> dict[str, Any]:
    """Attempt ccxt.fetch_balance() and return connection status + latency."""
    ex_id = body.exchange_id.lower()

    if ex_id == "polymarket":
        # Polymarket uses its own HTTP client — basic HTTP ping instead
        import httpx
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get("https://clob.polymarket.com/markets?limit=1")
            latency_ms = int((time.monotonic() - start) * 1000)
            connected = resp.status_code == 200
        except Exception as exc:  # noqa: BLE001
            logger.warning("polymarket_test_failed", exc=str(exc))
            connected, latency_ms = False, 0
        return {"connected": connected, "latency_ms": latency_ms}

    if ex_id not in ("binance", "coinbase", "kraken"):
        raise HTTPException(400, f"Unsupported exchange: {ex_id}")

    redis = get_redis()
    creds: dict[str, str] = await redis.hgetall(f"config:exchange:{ex_id}") or {}
    if not creds.get("api_key") or not creds.get("secret"):
        return {"connected": False, "latency_ms": 0, "error": "No credentials configured"}

    params: dict[str, object] = {
        "apiKey": creds["api_key"],
        "secret": creds["secret"],
    }
    if creds.get("passphrase"):
        params["password"] = creds["passphrase"]
    if creds.get("sandbox", "").strip().lower() in ("true", "1", "yes"):
        params["sandbox"] = True

    exchange_cls = getattr(ccxt_async, ex_id, None)
    if exchange_cls is None:
        return {"connected": False, "latency_ms": 0, "error": "Exchange class not found"}

    exchange = exchange_cls(params)
    start = time.monotonic()
    try:
        await exchange.fetch_balance()
        latency_ms = int((time.monotonic() - start) * 1000)
        connected = True
    except Exception as exc:  # noqa: BLE001
        latency_ms = int((time.monotonic() - start) * 1000)
        connected = False
        logger.warning("exchange_test_failed", exchange=ex_id, exc=str(exc))
    finally:
        await exchange.close()

    return {"connected": connected, "latency_ms": latency_ms}


# ── POST /api/settings/toggle-live ────────────────────────────────────────

class ToggleLiveRequest(BaseModel):
    confirm: bool = False


@router.post("/toggle-live")
async def toggle_live_trading(body: ToggleLiveRequest) -> dict[str, Any]:
    """Flip the paper_trading flag in Redis.

    Requires  {confirm: true}  in the request body to prevent accidental calls.
    Returns the new value of paper_trading.
    """
    if not body.confirm:
        raise HTTPException(400, "Must send {confirm: true} to toggle trading mode.")

    redis = get_redis()
    current = await redis.hget("config:system", "paper_trading")
    is_paper = (current or "true").strip().lower() not in ("false", "0", "no")
    new_value = "false" if is_paper else "true"
    await redis.hset("config:system", "paper_trading", new_value)

    new_mode = "paper" if new_value == "true" else "live"
    logger.warning("trading_mode_toggled", from_mode="paper" if is_paper else "live",
                   to_mode=new_mode)
    return {"paper_trading": new_value, "mode": new_mode}
