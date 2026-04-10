"""Vera — Technical Analyst agent stub."""
from typing import Any
from src.agents.base import BaseAgent


class VeraAgent(BaseAgent):
    name = "vera"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        # TODO: Implement technical analysis (Phase 1)
        return state
