"""Scout — Opportunities Agent stub."""
from typing import Any

from src.agents.base import BaseAgent


class ScoutAgent(BaseAgent):
    name = "scout"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        # TODO: Implement opportunity scanning (Phase 1)
        return state
