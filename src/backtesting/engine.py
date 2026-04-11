"""Event-driven backtesting engine."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Callable, Any

import structlog

from src.data.models.market import OHLCVBar
from src.backtesting.metrics import BacktestMetrics, calculate_metrics

logger = structlog.get_logger()


@dataclass
class BacktestTrade:
    symbol: str
    direction: str  # LONG or SHORT
    entry_price: float
    exit_price: float
    quantity: float
    entry_time: datetime
    exit_time: datetime
    pnl: float
    pnl_pct: float
    strategy_name: str
    exit_reason: str  # SIGNAL, STOP_LOSS, TAKE_PROFIT, END_OF_DATA


@dataclass
class BacktestPosition:
    symbol: str
    direction: str
    entry_price: float
    quantity: float
    entry_time: datetime
    stop_loss: float | None = None
    take_profit: float | None = None


@dataclass
class BacktestConfig:
    symbol: str
    exchange: str
    timeframe: str
    initial_equity: float = 10000.0
    commission_pct: float = 0.001   # 0.1%
    slippage_pct: float = 0.0005    # 0.05%
    max_position_pct: float = 0.02  # 2% risk per trade
    strategy_params: dict[str, Any] = field(default_factory=dict)


@dataclass
class BacktestResult:
    config: BacktestConfig
    trades: list[BacktestTrade]
    equity_curve: list[float]
    metrics: BacktestMetrics
    start_time: datetime
    end_time: datetime
    bars_processed: int
    # Memorization risk assessment — set by BacktestValidator after the run
    memorization_risk: str = "UNKNOWN"
    # Validity flags — adjusted Sharpe, warnings, labels
    validity_flags: dict = field(default_factory=dict)


class BacktestEngine:
    def __init__(self, config: BacktestConfig) -> None:
        self.config = config
        self._position: BacktestPosition | None = None
        self._equity = config.initial_equity
        self._equity_curve: list[float] = [config.initial_equity]
        self._trades: list[BacktestTrade] = []

    def _apply_slippage(self, price: float, is_buy: bool) -> float:
        slip = price * self.config.slippage_pct
        return price + slip if is_buy else price - slip

    def _apply_commission(self, value: float) -> float:
        return value * self.config.commission_pct

    def _enter_long(
        self,
        bar: OHLCVBar,
        stop_loss: float | None = None,
        take_profit: float | None = None,
    ) -> None:
        if self._position:
            return
        entry_price = self._apply_slippage(float(bar.close), is_buy=True)
        position_value = self._equity * self.config.max_position_pct
        quantity = position_value / entry_price
        commission = self._apply_commission(position_value)
        self._equity -= commission
        self._position = BacktestPosition(
            symbol=bar.symbol,
            direction="LONG",
            entry_price=entry_price,
            quantity=quantity,
            entry_time=bar.ts,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )
        logger.debug("backtest_enter_long", price=entry_price, quantity=quantity)

    def _exit_position(self, bar: OHLCVBar, reason: str) -> BacktestTrade | None:
        if not self._position:
            return None
        exit_price = self._apply_slippage(float(bar.close), is_buy=False)
        pos_value = self._position.quantity * exit_price
        commission = self._apply_commission(pos_value)
        entry_value = self._position.quantity * self._position.entry_price
        pnl = pos_value - entry_value - commission
        pnl_pct = pnl / entry_value * 100
        self._equity += pnl
        trade = BacktestTrade(
            symbol=self._position.symbol,
            direction=self._position.direction,
            entry_price=self._position.entry_price,
            exit_price=exit_price,
            quantity=self._position.quantity,
            entry_time=self._position.entry_time,
            exit_time=bar.ts,
            pnl=pnl,
            pnl_pct=pnl_pct,
            strategy_name=self.config.strategy_params.get("name", "default"),
            exit_reason=reason,
        )
        self._trades.append(trade)
        self._position = None
        return trade

    def _check_stops(self, bar: OHLCVBar) -> bool:
        if not self._position:
            return False
        low, high = float(bar.low), float(bar.high)
        if self._position.stop_loss and low <= self._position.stop_loss:
            self._exit_position(bar, "STOP_LOSS")
            return True
        if self._position.take_profit and high >= self._position.take_profit:
            self._exit_position(bar, "TAKE_PROFIT")
            return True
        return False

    async def run(
        self,
        bars: list[OHLCVBar],
        strategy_fn: Callable[[OHLCVBar, list[OHLCVBar]], dict | None],
    ) -> BacktestResult:
        if not bars:
            raise ValueError("No bars provided")
        history: list[OHLCVBar] = []
        start_time = bars[0].ts
        for bar in bars:
            self._equity_curve.append(self._equity)
            self._check_stops(bar)
            signal = strategy_fn(bar, history)
            if signal:
                action = signal.get("action")
                if action == "BUY" and not self._position:
                    self._enter_long(bar, signal.get("stop_loss"), signal.get("take_profit"))
                elif action == "SELL" and self._position:
                    self._exit_position(bar, "SIGNAL")
            history.append(bar)
        if self._position:
            self._exit_position(bars[-1], "END_OF_DATA")
        years = max((bars[-1].ts - start_time).days / 365, 1 / 365)
        metrics = calculate_metrics(
            [{"pnl": t.pnl} for t in self._trades],
            self._equity_curve,
            self.config.initial_equity,
            years,
        )
        result = BacktestResult(
            config=self.config,
            trades=self._trades,
            equity_curve=self._equity_curve,
            metrics=metrics,
            start_time=start_time,
            end_time=bars[-1].ts,
            bars_processed=len(bars),
        )

        # --- Memorization risk assessment ---
        # Run after the backtest so we can annotate the result in-place.
        # This does NOT change the backtest outcome — it flags the result for consumers.
        from src.backtesting.validation import BacktestValidator
        validator = BacktestValidator()
        risk = validator.check_memorization_risk(
            symbol=self.config.symbol,
            start_date=start_time,
            end_date=bars[-1].ts,
        )
        result.memorization_risk = risk["risk_level"]
        result.validity_flags = validator.validate_backtest_result(result, risk["risk_level"])

        if risk["risk_level"] != "LOW":
            logger.warning(
                "backtest_memorization_risk",
                symbol=self.config.symbol,
                risk_level=risk["risk_level"],
                reason=risk["reason"][:120],
            )

        return result
