"""Rex — Sentiment Analyst agent stub."""
from typing import Any
from src.agents.base import BaseAgent


class RexAgent(BaseAgent):
    name = "rex"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        # TODO: Implement sentiment analysis (Phase 1)
        return state
