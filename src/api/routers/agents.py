"""Agents API router — implemented fully in Phase 3."""
from fastapi import APIRouter

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("")
async def list_agents() -> list[dict]:
    """List all agents with placeholder status."""
    agents = [
        {"id": "marcus", "name": "Marcus", "role": "Fundamentals Analyst", "status": "idle", "elo": 1200},
        {"id": "vera", "name": "Vera", "role": "Technical Analyst", "status": "idle", "elo": 1200},
        {"id": "rex", "name": "Rex", "role": "Sentiment Analyst", "status": "idle", "elo": 1200},
        {"id": "diana", "name": "Diana", "role": "Risk Manager", "status": "idle", "elo": 1200},
        {"id": "atlas", "name": "Atlas", "role": "Execution", "status": "idle", "elo": 1200},
        {"id": "nova", "name": "Nova", "role": "Options", "status": "idle", "elo": 1200},
        {"id": "bull", "name": "Bull", "role": "Bullish Researcher", "status": "idle", "elo": 1200},
        {"id": "bear", "name": "Bear", "role": "Bearish Researcher", "status": "idle", "elo": 1200},
        {"id": "sage", "name": "Sage", "role": "Supervisor", "status": "idle", "elo": 1200},
        {"id": "scout", "name": "Scout", "role": "Opportunities", "status": "idle", "elo": 1200},
    ]
    return agents
