"""Atlas — Execution Agent stub."""
from typing import Any
from src.agents.base import BaseAgent


class AtlasAgent(BaseAgent):
    name = "atlas"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        # TODO: Implement order execution (Phase 1)
        return state
