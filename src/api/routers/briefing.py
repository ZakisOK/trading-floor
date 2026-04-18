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

        portfolio_val = await paper_broker.get_portfolio_value()
        daily_pnl = await paper_broker.get_daily_pnl()
        n_positions = len(await paper_broker.get_positions())

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


@router.get("/opportunities")
async def get_opportunities() -> dict:
    """Run Scout overnight scan and return top-ranked proposals."""
    try:
        from src.agents.scout import ScoutAgent
        from src.core.database import get_session
        from src.data.repositories.ohlcv_repo import OHLCVRepository
        from datetime import timedelta

        SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT"]
        scout = ScoutAgent()
        bars_by_symbol: dict = {}

        async for session in get_session():
            repo = OHLCVRepository(session)
            end = datetime.now(UTC)
            start = end - timedelta(days=30)
            for sym in SYMBOLS:
                bars = await repo.get_bars(sym, "binance", "1h", start, end, limit=720)
                if bars:
                    bars_by_symbol[sym] = bars

        proposals = await scout.scan_opportunities(SYMBOLS, bars_by_symbol)
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "symbols_scanned": len(SYMBOLS),
            "proposals": proposals,
        }
    except Exception as e:
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "symbols_scanned": 0,
            "proposals": [],
            "error": str(e),
        }
