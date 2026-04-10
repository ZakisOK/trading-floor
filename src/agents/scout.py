"""Scout — Opportunities Agent — scans symbols and surfaces backtested proposals."""
from __future__ import annotations

import structlog
from anthropic import AsyncAnthropic

from src.agents.base import BaseAgent, AgentState
from src.core.config import settings
from src.backtesting.engine import BacktestEngine, BacktestConfig
from src.backtesting.strategies import AVAILABLE_STRATEGIES
from src.data.models.market import OHLCVBar

logger = structlog.get_logger()


class ScoutAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("scout", "Scout", "Opportunities Agent")
        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def scan_opportunities(
        self,
        symbols: list[str],
        bars_by_symbol: dict[str, list[OHLCVBar]],
    ) -> list[dict]:
        """Scan symbols, backtest top strategies, surface the best proposals."""
        proposals = []
        for symbol in symbols:
            bars = bars_by_symbol.get(symbol, [])
            if len(bars) < 50:
                logger.info("scout_skip", symbol=symbol, bars=len(bars))
                continue
            for strategy_name, strategy_factory in AVAILABLE_STRATEGIES.items():
                try:
                    config = BacktestConfig(symbol=symbol, exchange="binance", timeframe="1h")
                    engine = BacktestEngine(config)
                    result = await engine.run(bars, strategy_factory())
                    m = result.metrics
                    if m.sharpe_ratio > 1.0 and m.win_rate > 50 and m.total_trades >= 5:
                        proposals.append({
                            "symbol": symbol,
                            "strategy": strategy_name,
                            "sharpe": round(m.sharpe_ratio, 3),
                            "win_rate": round(m.win_rate, 1),
                            "total_return_pct": round(m.total_return_pct, 2),
                            "max_drawdown_pct": round(m.max_drawdown_pct, 2),
                            "total_trades": m.total_trades,
                            "confidence": round(min(m.sharpe_ratio / 3, 0.95), 3),
                        })
                except Exception as e:
                    logger.error("scout_backtest_error", symbol=symbol, strategy=strategy_name, error=str(e))

        proposals.sort(key=lambda x: x["sharpe"], reverse=True)
        return proposals[:5]

    async def analyze(self, state: AgentState) -> AgentState:
        """No-op in the standard pipeline — Scout is called via scan_opportunities."""
        return state
