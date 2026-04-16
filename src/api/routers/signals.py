"""Signals API — recent agent signals from Redis stream."""
from __future__ import annotations

from fastapi import APIRouter, Query

from src.core.redis import get_redis

router = APIRouter(prefix="/api/signals", tags=["signals"])


@router.get("/recent")
async def get_recent_signals(limit: int = Query(default=10, ge=1, le=200)) -> list[dict]:
    """Return the most recent N signals across all agents."""
    redis = get_redis()
    try:
        msgs = await redis.xrevrange("stream:signals:raw", count=limit)
    except Exception:
        return []

    out: list[dict] = []
    for msg_id, fields in msgs:
        try:
            confidence = float(fields.get("confidence", 0) or 0)
        except (TypeError, ValueError):
            confidence = 0.0
        out.append({
            "id": msg_id,
            "agent": fields.get("agent_id") or fields.get("agent") or "unknown",
            "symbol": fields.get("symbol"),
            "direction": fields.get("direction"),
            "confidence": confidence,
            "thesis": fields.get("thesis"),
            "asset_class": fields.get("asset_class"),
            "signal_type": fields.get("signal_type"),
            "ts": fields.get("_ts") or fields.get("ts"),
        })
    return out
