"""Desk tasks router — what each desk has queued, in-flight, recently done."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter

from src.core.redis import get_redis

router = APIRouter(prefix="/api/desks", tags=["desks"])

# Schedule mirrors scripts/run_paper_trading.py
_SCHEDULE: dict[str, int] = {
    "XRP/USDT": 120,
    "BTC/USDT": 300,
    "ETH/USDT": 300,
    "SOL/USDT": 300,
    "ADA/USDT": 600,
    "AVAX/USDT": 600,
    "DOGE/USDT": 600,
    "LINK/USDT": 600,
    "DOT/USDT": 600,
    "UNI/USDT": 600,
    "GC=F": 900,
    "SI=F": 900,
    "CL=F": 900,
    "NG=F": 900,
    "HG=F": 900,
}

# Desk assignments — each desk participates in every cycle but in a different stage
_DESK_AGENTS = {
    "research": ["marcus", "vera", "rex", "xrp_analyst", "polymarket_scout", "nova"],
    "execution": ["diana", "atlas"],
    "oversight": ["sage", "scout"],
}
_DESK_LABEL = {
    "research": "Alpha Research",
    "execution": "Trade Execution",
    "oversight": "Portfolio Oversight",
}


def _desk_for_agent(agent_id: str) -> str | None:
    for desk, agents in _DESK_AGENTS.items():
        if agent_id in agents:
            return desk
    return None


@router.get("/tasks")
async def desk_tasks() -> dict:
    """Return scheduled, in-progress, and recent completions by desk."""
    redis = get_redis()
    now = datetime.now(UTC)

    # ── Queue: next run per symbol ──
    queue = []
    for sym, interval in _SCHEDULE.items():
        last_raw = await redis.get(f"schedule:last_run:{sym}")
        if last_raw:
            last = datetime.fromisoformat(last_raw)
        else:
            last = now - timedelta(seconds=interval)
        next_run = last + timedelta(seconds=interval)
        seconds_until = max(0, (next_run - now).total_seconds())
        queue.append({
            "symbol": sym,
            "interval_s": interval,
            "last_run": last.isoformat(),
            "next_run": next_run.isoformat(),
            "seconds_until_next": round(seconds_until, 1),
            "is_running_now": bool(await redis.get(f"schedule:started:{sym}")) and seconds_until > interval - 5,
        })
    queue.sort(key=lambda x: x["seconds_until_next"])

    # ── In-flight: agents actively working ──
    in_progress = []
    all_agents = [a for agents in _DESK_AGENTS.values() for a in agents]
    for agent_id in all_agents:
        state = await redis.hgetall(f"agent:state:{agent_id}")
        if state and state.get("status") == "active":
            in_progress.append({
                "agent": agent_id,
                "desk": _desk_for_agent(agent_id),
                "symbol": state.get("current_task") or None,
                "since": state.get("last_heartbeat"),
            })

    # ── Recent completions ──
    raw = await redis.lrange("schedule:completions", 0, 9)
    recent: list[dict] = []
    for item in raw:
        try:
            recent.append(json.loads(item))
        except (json.JSONDecodeError, TypeError):
            continue

    # ── Per-desk summary ──
    desks = []
    for key, agents in _DESK_AGENTS.items():
        desk_active = [p for p in in_progress if p["desk"] == key]
        desks.append({
            "key": key,
            "label": _DESK_LABEL[key],
            "agents": agents,
            "active_count": len(desk_active),
            "active": desk_active,
        })

    return {
        "ts": now.isoformat(),
        "queue": queue,
        "in_progress": in_progress,
        "desks": desks,
        "recent_completions": recent,
    }
