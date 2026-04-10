"""Kill switch and security utilities."""
from __future__ import annotations

from datetime import datetime, UTC
import structlog

from src.streams.producer import produce_audit
from src.core.redis import get_redis

logger = structlog.get_logger()


async def activate_kill_switch(
    reason: str, operator_id: str = "operator"
) -> dict:
    """Activate the emergency kill switch — stops all new order processing."""
    redis = get_redis()
    await redis.set("kill_switch:active", "1")
    await redis.set("kill_switch:reason", reason)
    await redis.set("kill_switch:activated_at", datetime.now(UTC).isoformat())
    await produce_audit(
        "kill_switch_activated", operator_id, {"reason": reason}, redis=redis
    )
    logger.critical("kill_switch_activated", reason=reason, operator=operator_id)
    return {
        "status": "activated",
        "reason": reason,
        "ts": datetime.now(UTC).isoformat(),
    }


async def is_kill_switch_active() -> bool:
    """Check whether the kill switch is currently active."""
    redis = get_redis()
    val = await redis.get("kill_switch:active")
    return val in (b"1", "1")


async def reset_kill_switch(operator_id: str = "operator") -> dict:
    """Reset the kill switch — re-enables order processing."""
    redis = get_redis()
    await redis.delete("kill_switch:active")
    await redis.delete("kill_switch:reason")
    await produce_audit("kill_switch_reset", operator_id, {}, redis=redis)
    logger.info("kill_switch_reset", operator=operator_id)
    return {"status": "reset"}


async def get_kill_switch_status() -> dict:
    """Return current kill switch state."""
    redis = get_redis()
    active = await is_kill_switch_active()
    reason = await redis.get("kill_switch:reason") or ""
    activated_at = await redis.get("kill_switch:activated_at") or ""
    return {
        "active": active,
        "reason": reason,
        "activated_at": activated_at,
    }
