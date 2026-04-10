"""Nova — Options Strategist agent stub."""
from typing import Any
from src.agents.base import BaseAgent


class NovaAgent(BaseAgent):
    name = "nova"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        # TODO: Implement options strategy (Phase 1)
        return state
