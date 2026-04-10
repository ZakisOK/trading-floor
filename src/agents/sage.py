"""Sage — Portfolio Manager (LangGraph supervisor) stub."""
from typing import Any

from src.agents.base import BaseAgent


class SageAgent(BaseAgent):
    """Supervisor agent that orchestrates all other agents via LangGraph."""

    name = "sage"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        # TODO: Implement LangGraph supervisor graph (Phase 1)
        return state
