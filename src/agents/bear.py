"""Bear — Bearish Researcher agent."""
from __future__ import annotations

import json
import structlog
from anthropic import AsyncAnthropic
from src.agents.base import BaseAgent, AgentState
from src.core.config import settings

logger = structlog.get_logger()


class BearAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("bear", "Bear", "Bearish Researcher")
        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def analyze(self, state: AgentState) -> AgentState:
        market = state.get("market_data") or {}
        symbol = market.get("symbol", "UNKNOWN")
        prompt = (
            f"You are Bear, a cautious risk-focused researcher. Symbol: {symbol}.\n"
            f"Make the strongest possible bearish case. Respond ONLY in JSON:\n"
            f'{{\"thesis\": \"...\", \"risks\": [\"...\"], \"confidence\": 0.75}}'
        )
        try:
            resp = await self._client.messages.create(
                model="claude-haiku-4-5-20251001", max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.content[0].text
            start, end = text.find("{"), text.rfind("}") + 1
            data = json.loads(text[start:end]) if start >= 0 else {}
            updated = dict(state)
            updated["messages"] = list(state.get("messages", [])) + [{
                "from": self.name, "role": "bearish",
                "thesis": data.get("thesis", "Bearish outlook"),
                "confidence": data.get("confidence", 0.7),
            }]
            return AgentState(**updated)
        except Exception as e:
            logger.error("bear_error", error=str(e))
            return state
