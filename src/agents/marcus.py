"""Marcus — Fundamentals Analyst agent stub."""
from typing import Any
from src.agents.base import BaseAgent


class MarcusAgent(BaseAgent):
    name = "marcus"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        # TODO: Implement fundamentals analysis (Phase 1)
        return state
