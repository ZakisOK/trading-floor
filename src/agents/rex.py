"""Rex — Sentiment Analyst agent."""
from __future__ import annotations

import json
from datetime import UTC, datetime

import structlog
from anthropic import AsyncAnthropic

from src.agents.base import BaseAgent, AgentState
from src.core.config import settings
from src.core.redis import get_redis

logger = structlog.get_logger()


class RexAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("rex", "Rex", "Sentiment Analyst")
        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def analyze(self, state: AgentState) -> AgentState:
        market = state.get("market_data") or {}
        symbol = market.get("symbol", "UNKNOWN")
        signals = state.get("signals", [])
        prompt = (
            f"You are Rex, a sentiment analyst. Symbol: {symbol}.\n"
            f"Analyst signals so far: {signals}\n"
            f"Assess market sentiment and crowd psychology. Respond ONLY in JSON:\n"
            f'{{\"direction\": \"LONG\", \"confidence\": 0.6, \"thesis\": \"...\", \"sentiment_score\": 0.7}}'
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
            thesis = data.get("thesis", "Neutral sentiment")
            score = float(data.get("sentiment_score", 0.0))
            label = "BULLISH" if score > 0.2 else "BEARISH" if score < -0.2 else "NEUTRAL"

            # Publish sentiment to Redis so /api/market/sentiment/{symbol} has data
            safe_sym = symbol.replace("/", "_").replace("=", "_")
            payload = {
                "score": score,
                "label": label,
                "confidence": confidence,
                "headlines": [],
                "thesis": thesis,
                "ts": datetime.now(UTC).isoformat(),
            }
            redis = get_redis()
            await redis.setex(f"sentiment:{safe_sym}", 3600, json.dumps(payload))

            await self.emit_signal(symbol, direction, confidence, thesis, "sentiment")
            updated = dict(state)
            updated["signals"] = list(state.get("signals", [])) + [
                {"agent": self.name, "direction": direction, "confidence": confidence, "thesis": thesis}
            ]
            return AgentState(**updated)
        except Exception as e:
            logger.error("rex_analyze_error", error=str(e))
            return state
