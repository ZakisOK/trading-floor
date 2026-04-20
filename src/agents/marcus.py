"""Marcus — Fundamentals Analyst agent."""
from __future__ import annotations

import json
import structlog
from src.core.llm_costs import make_tracked_client

from src.agents.base import BaseAgent, AgentState
from src.core.config import settings

logger = structlog.get_logger()


_PROMPT_SKELETON = (
    "You are Marcus, a fundamentals analyst at a trading firm.\n"
    "Symbol/price/market context vary per cycle.\n"
    "Output schema: direction, confidence, thesis, risk."
)


class MarcusAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(
            "marcus",
            "Marcus",
            "Fundamentals Analyst",
            model_name="claude-haiku-4-5-20251001",
            prompt_template=_PROMPT_SKELETON,
        )
        self._client = make_tracked_client(api_key=settings.anthropic_api_key)

    async def analyze(self, state: AgentState) -> AgentState:
        market = state.get("market_data") or {}
        symbol = market.get("symbol", "UNKNOWN")
        close = market.get("close", 0)
        prompt = (
            f"You are Marcus, a fundamentals analyst at a trading firm.\n"
            f"Symbol: {symbol}, Current Price: {close}\n"
            f"Market context: {market}\n\n"
            f"Analyze the fundamental outlook. Respond ONLY in JSON:\n"
            f'{{\"direction\": \"LONG\", \"confidence\": 0.72, \"thesis\": \"...\", \"risk\": \"...\"}}'
        )
        try:
            resp = await self._client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.content[0].text
            start, end = text.find("{"), text.rfind("}") + 1
            data = json.loads(text[start:end]) if start >= 0 else {}
            direction = data.get("direction", "NEUTRAL")
            confidence = float(data.get("confidence", 0.5))
            thesis = data.get("thesis", "No thesis available")
            await self.emit_signal(symbol, direction, confidence, thesis, "fundamentals")
            updated = dict(state)
            updated["signals"] = list(state.get("signals", [])) + [
                {"agent": self.name, "direction": direction, "confidence": confidence, "thesis": thesis}
            ]
            return AgentState(**updated)
        except Exception as e:
            logger.error("marcus_analyze_error", error=str(e))
            return state
