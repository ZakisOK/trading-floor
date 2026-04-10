"""Bear — Bear Researcher agent stub."""
from typing import Any
from src.agents.base import BaseAgent


class BearAgent(BaseAgent):
    name = "bear"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        # TODO: Implement bear case research (Phase 1)
        return state
