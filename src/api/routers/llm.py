"""LLM usage + cost router."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter

from src.core.redis import get_redis

router = APIRouter(prefix="/api/llm", tags=["llm"])


def _safe_int(v: str | bytes | None) -> int:
    try:
        return int(v) if v is not None else 0
    except (TypeError, ValueError):
        return 0


def _safe_float(v: str | bytes | None) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


@router.get("/costs")
async def get_costs() -> dict:
    """Return today's + all-time LLM spend and token counts."""
    redis = get_redis()
    today = date.today().isoformat()
    cost_today = _safe_float(await redis.get(f"llm:cost:{today}"))
    cost_all = _safe_float(await redis.get("llm:cost:all"))
    calls_today = _safe_int(await redis.get(f"llm:calls:{today}"))
    calls_all = _safe_int(await redis.get("llm:calls:all"))
    input_today = _safe_int(await redis.get(f"llm:tokens:input:{today}"))
    output_today = _safe_int(await redis.get(f"llm:tokens:output:{today}"))
    input_all = _safe_int(await redis.get("llm:tokens:input:all"))
    output_all = _safe_int(await redis.get("llm:tokens:output:all"))

    by_model_today_raw = await redis.hgetall(f"llm:by_model:{today}") or {}
    by_model_today: dict[str, dict[str, int]] = {}
    for k, v in by_model_today_raw.items():
        if ":" in k:
            model, field = k.rsplit(":", 1)
            by_model_today.setdefault(model, {})[field] = _safe_int(v)

    # 7-day history
    history = []
    for i in range(7):
        d = (date.today() - timedelta(days=i)).isoformat()
        history.append({
            "date": d,
            "cost": _safe_float(await redis.get(f"llm:cost:{d}")),
            "calls": _safe_int(await redis.get(f"llm:calls:{d}")),
            "input": _safe_int(await redis.get(f"llm:tokens:input:{d}")),
            "output": _safe_int(await redis.get(f"llm:tokens:output:{d}")),
        })

    return {
        "today": {
            "cost_usd": round(cost_today, 4),
            "calls": calls_today,
            "input_tokens": input_today,
            "output_tokens": output_today,
            "by_model": by_model_today,
        },
        "all_time": {
            "cost_usd": round(cost_all, 4),
            "calls": calls_all,
            "input_tokens": input_all,
            "output_tokens": output_all,
        },
        "history_7d": history,
        "ts": datetime.now(UTC).isoformat(),
    }
