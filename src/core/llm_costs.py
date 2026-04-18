"""LLM cost tracker — wraps the Anthropic SDK and records token usage + cost.

Every agent in the system uses `AsyncAnthropic().messages.create(...)`. We
install a lightweight wrapper that records input/output tokens per call into
Redis, plus a rolling daily cost. The dashboard reads from here.

Usage: replace `make_tracked_client(api_key=...)` with
`make_tracked_client(api_key=...)` in agents (or patch globally).
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import structlog

from anthropic import AsyncAnthropic
from anthropic.types import Message

from src.core.redis import get_redis

logger = structlog.get_logger()

# Approximate pricing per 1M tokens (USD). Keep in sync with
# https://www.anthropic.com/pricing
_PRICES: dict[str, tuple[float, float]] = {
    # model: (input_per_1M, output_per_1M)
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-7": (15.0, 75.0),
    "claude-opus-4-7[1m]": (15.0, 75.0),
}


def _price_for(model: str) -> tuple[float, float]:
    if model in _PRICES:
        return _PRICES[model]
    for prefix, price in _PRICES.items():
        if model.startswith(prefix.split("-")[0:3][-1]):
            return price
    return (3.0, 15.0)  # default to Sonnet-ish


async def record_usage(model: str, input_tokens: int, output_tokens: int) -> dict[str, float]:
    """Persist token usage + dollar cost to Redis. Returns the computed cost."""
    price_in, price_out = _price_for(model)
    cost_usd = (input_tokens / 1_000_000) * price_in + (output_tokens / 1_000_000) * price_out
    today = date.today().isoformat()
    redis = get_redis()
    pipe = redis.pipeline()
    pipe.incrby(f"llm:tokens:input:{today}", input_tokens)
    pipe.incrby(f"llm:tokens:output:{today}", output_tokens)
    pipe.incrbyfloat(f"llm:cost:{today}", cost_usd)
    pipe.incrby(f"llm:calls:{today}", 1)
    pipe.hincrby(f"llm:by_model:{today}", f"{model}:calls", 1)
    pipe.hincrby(f"llm:by_model:{today}", f"{model}:input", input_tokens)
    pipe.hincrby(f"llm:by_model:{today}", f"{model}:output", output_tokens)
    pipe.incrby("llm:tokens:input:all", input_tokens)
    pipe.incrby("llm:tokens:output:all", output_tokens)
    pipe.incrbyfloat("llm:cost:all", cost_usd)
    pipe.incrby("llm:calls:all", 1)
    await pipe.execute()
    return {"cost_usd": cost_usd, "input": input_tokens, "output": output_tokens, "model": model}


class TrackedMessages:
    """Proxy that wraps messages.create with usage tracking."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    async def create(self, *args: Any, **kwargs: Any) -> Message:
        agent_id = kwargs.pop("_agent_id", None)
        model = kwargs.get("model", "unknown")
        resp: Message = await self._inner.create(*args, **kwargs)
        try:
            usage = getattr(resp, "usage", None)
            input_t = getattr(usage, "input_tokens", 0) or 0
            output_t = getattr(usage, "output_tokens", 0) or 0
            await record_usage(model, input_t, output_t)
            if agent_id:
                redis = get_redis()
                await redis.hincrbyfloat(
                    f"agent:state:{agent_id}", "llm_cost",
                    (input_t / 1_000_000) * _price_for(model)[0]
                    + (output_t / 1_000_000) * _price_for(model)[1],
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("llm_cost_tracking_failed", error=str(exc))
        return resp

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class TrackedAnthropic:
    """Drop-in replacement for AsyncAnthropic that tracks cost per call."""

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        self._client = AsyncAnthropic(api_key=api_key, **kwargs)
        self.messages = TrackedMessages(self._client.messages)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


def make_tracked_client(api_key: str | None = None, **kwargs: Any) -> TrackedAnthropic:
    return TrackedAnthropic(api_key=api_key, **kwargs)
