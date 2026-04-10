"""Bull — Bull Researcher agent stub."""
from typing import Any
from src.agents.base import BaseAgent


class BullAgent(BaseAgent):
    name = "bull"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        # TODO: Implement bull case research (Phase 1)
        return state
