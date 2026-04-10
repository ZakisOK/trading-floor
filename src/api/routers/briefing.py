"""Morning briefing API — AI-generated daily summary."""
from __future__ import annotations

from datetime import datetime, UTC
from fastapi import APIRouter

router = APIRouter(prefix="/api/briefing", tags=["briefing"])


@router.get("")
async def get_briefing() -> dict:
    """Generate AI morning briefing using available data."""
    try:
        from anthropic import AsyncAnthropic
        from src.core.config import settings
        from src.core.redis import get_redis
        from src.execution.broker import paper_broker

        redis = get_redis()
        raw_signals = await redis.xrevrange("stream:signals:raw", count=20)
        signal_summaries = []
        for _msg_id, fields in raw_signals:
            signal_summaries.append(
                f"{fields.get('agent_name','?')}: {fields.get('direction','?')} "
                f"{fields.get('symbol','?')} @ {fields.get('confidence','?')} confidence"
            )

        portfolio_val = paper_broker.get_portfolio_value()
        daily_pnl = paper_broker._daily_pnl
        n_positions = len(paper_broker.get_positions())

        prompt = (
            f"You are the Trading Floor morning briefing system. Today is {datetime.now(UTC).strftime('%A, %B %d %Y')}.\n\n"
            f"Portfolio: ${portfolio_val:,.2f} | Daily P&L: ${daily_pnl:+.2f} | Open positions: {n_positions}\n"
            f"Recent signals:\n" + "\n".join(signal_summaries[:10] or ["No signals yet"]) +
            "\n\nGenerate a concise morning briefing in JSON:\n"
            '{"summary": "...", "key_risks": ["..."], "opportunities": ["..."], "recommendation": "..."}'
        )

        client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        resp = await client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        import json
        text = resp.content[0].text
        start, end = text.find("{"), text.rfind("}") + 1
        data = json.loads(text[start:end]) if start >= 0 else {}
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "portfolio_value": portfolio_val,
            "daily_pnl": daily_pnl,
            "open_positions": n_positions,
            **data,
        }
    except Exception as e:
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "summary": f"Briefing unavailable: {str(e)}",
            "key_risks": [], "opportunities": [], "recommendation": "Check system status",
        }
