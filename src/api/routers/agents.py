"""Agents API router — Phase 3 full implementation."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.core.redis import get_redis
from src.agents.sage import run_trading_cycle

router = APIRouter(prefix="/api/agents", tags=["agents"])

_AGENT_META = [
    {"id": "marcus", "name": "Marcus", "role": "Fundamentals Analyst", "color": "#9677D0"},
    {"id": "vera",   "name": "Vera",   "role": "Technical Analyst",    "color": "#643588"},
    {"id": "rex",    "name": "Rex",    "role": "Sentiment Analyst",     "color": "#9677D0"},
    {"id": "diana",  "name": "Diana",  "role": "Risk Manager",          "color": "#ED6F91"},
    {"id": "atlas",  "name": "Atlas",  "role": "Execution",             "color": "#3EB6B0"},
    {"id": "nova",   "name": "Nova",   "role": "Options & Volatility",  "color": "#3EB6B0"},
    {"id": "bull",   "name": "Bull",   "role": "Bullish Researcher",    "color": "#E3A535"},
    {"id": "bear",   "name": "Bear",   "role": "Bearish Researcher",    "color": "#E3A535"},
    {"id": "sage",   "name": "Sage",   "role": "Supervisor",            "color": "#F89318"},
    {"id": "scout",  "name": "Scout",  "role": "Opportunities",         "color": "#38BDF8"},
]


@router.get("")
async def list_agents() -> list[dict]:
    """List all agents with live status from Redis."""
    redis = get_redis()
    agents = []
    for meta in _AGENT_META:
        state_key = f"agent:state:{meta['id']}"
        raw = await redis.hgetall(state_key)
        wins = int(raw.get("trades_win", 0) or 0)
        losses = int(raw.get("trades_loss", 0) or 0)
        draws = int(raw.get("trades_draw", 0) or 0)
        total = wins + losses + draws
        agents.append({
            **meta,
            "status": raw.get("status", "idle"),
            "last_heartbeat": raw.get("last_heartbeat", None),
            "elo": float(raw.get("elo", 1200)),
            "current_task": raw.get("current_task", None),
            "trades_win": wins,
            "trades_loss": losses,
            "trades_draw": draws,
            "win_rate": wins / total if total else None,
        })
    return agents


class CycleRequest(BaseModel):
    symbol: str = "BTC/USDT"
    close: float = 50000.0
    volume: float = 1000.0


@router.post("/cycle")
async def run_cycle(req: CycleRequest) -> dict:
    """Run full multi-agent trading cycle via Sage."""
    result = await run_trading_cycle(req.symbol, {
        "close": req.close,
        "volume": req.volume,
    })
    return {
        "symbol": req.symbol,
        "signals": result.get("signals", []),
        "risk_approved": result.get("risk_approved", False),
        "final_decision": result.get("final_decision"),
        "confidence": result.get("confidence", 0.0),
        "reasoning": result.get("reasoning", ""),
    }


@router.get("/{agent_id}/signals")
async def get_agent_signals(agent_id: str) -> list[dict]:
    """Return recent signals emitted by an agent (from Redis stream)."""
    redis = get_redis()
    try:
        msgs = await redis.xrevrange("stream:signals:raw", count=50)
        signals = []
        for _msg_id, fields in msgs:
            if fields.get("agent_id") == agent_id:
                signals.append({
                    "symbol": fields.get("symbol"),
                    "direction": fields.get("direction"),
                    "confidence": fields.get("confidence"),
                    "thesis": fields.get("thesis"),
                    "ts": fields.get("_ts"),
                })
        return signals
    except Exception:
        return []


@router.post("/{agent_id}/run")
async def trigger_agent(agent_id: str, req: CycleRequest) -> dict:
    """Trigger a single agent analysis (runs full cycle, returns that agent's signal)."""
    result = await run_trading_cycle(req.symbol, {"close": req.close})
    signals = [s for s in result.get("signals", []) if s.get("agent", "").lower() == agent_id]
    return {"agent_id": agent_id, "signals": signals}
