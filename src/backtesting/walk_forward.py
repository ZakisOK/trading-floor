"""
Walk-forward validation — the industry standard for strategy validation.

Why static train/test splits fail:
  A single 80/20 split lets you overfit the 80% and "validate" on a 20% window
  that was implicitly shaped by parameter choices. The result looks good but
  performs poorly live because the test period is not truly independent.

Walk-forward validation fixes this:
  1. Split data into N equal windows (e.g., 12 months = 4 x 3-month windows)
  2. For each window:
     a. Train/optimize on the first 70% (in-sample)
     b. Test on the remaining 30% (out-of-sample)
     c. Record only out-of-sample metrics
  3. Aggregate out-of-sample metrics across all windows → true performance estimate

Key diagnostic — the degradation ratio:
  degradation_ratio = in_sample_sharpe / out_of_sample_sharpe

  1.0 = no degradation (the strategy generalizes perfectly — extremely rare)
  < 2.0 = acceptable — strategy is ROBUST, minor IS/OOS gap
  2.0–3.0 = caution — strategy is moderately overfit
  > 3.0 = MASSIVELY OVERFIT — do not trade live

If out_of_sample_sharpe < 0, the strategy loses money on unseen data.
This is the most common outcome for overfit strategies and a hard stop.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import structlog

from src.data.models.market import OHLCVBar
from src.backtesting.engine import BacktestEngine, BacktestConfig

logger = structlog.get_logger()


@dataclass
class WindowResult:
    """Metrics for a single walk-forward window."""
    window_index: int
    in_sample_sharpe: float
    out_of_sample_sharpe: float
    in_sample_bars: int
    out_of_sample_bars: int
    in_sample_trades: int
    out_of_sample_trades: int
    in_sample_start: str = ""
    in_sample_end: str = ""
    out_of_sample_start: str = ""
    out_of_sample_end: str = ""


@dataclass
class WalkForwardResult:
    """Aggregated result across all walk-forward windows."""
    symbol: str
    strategy_name: str
    n_windows: int
    in_sample_sharpe: float        # average IS Sharpe across all windows
    out_of_sample_sharpe: float    # average OOS Sharpe across all windows
    degradation_ratio: float       # IS / OOS — closer to 1.0 is better
    window_results: list[WindowResult] = field(default_factory=list)
    is_robust: bool = False        # True if OOS Sharpe > 0 AND degradation < 2.0
    total_bars: int = 0


class WalkForwardValidator:
    """
    Runs walk-forward validation on a strategy to detect overfitting.

    Usage:
        validator = WalkForwardValidator()
        result = await validator.run(
            symbol="XRP/USDT",
            strategy_fn=xrp_momentum(lookback=20),
            bars=bars,
            n_windows=4,
            train_pct=0.7,
        )
        print(f"OOS Sharpe: {result.out_of_sample_sharpe:.2f}")
        print(f"Robust: {result.is_robust}")
    """

    async def run(
        self,
        symbol: str,
        strategy_fn: Callable,
        bars: list[OHLCVBar],
        n_windows: int = 4,
        train_pct: float = 0.7,
        initial_equity: float = 10000.0,
    ) -> WalkForwardResult:
        """
        Run walk-forward validation.

        Args:
            symbol:         Trading symbol (used for logging and result labeling)
            strategy_fn:    Strategy function with signature (bar, history) -> dict | None
            bars:           Full list of OHLCV bars, ordered oldest to newest
            n_windows:      Number of walk-forward windows (default: 4)
            train_pct:      Fraction of each window used for in-sample training (default: 0.7)
            initial_equity: Starting equity per window (default: 10000)

        Returns:
            WalkForwardResult with per-window breakdown and aggregate IS/OOS metrics
        """
        min_bars = n_windows * 20
        if len(bars) < min_bars:
            raise ValueError(
                f"Need at least {min_bars} bars for {n_windows} windows "
                f"(got {len(bars)}). Reduce n_windows or fetch more data."
            )

        strategy_name = getattr(strategy_fn, "__name__", "unknown_strategy")
        window_size = len(bars) // n_windows
        window_results: list[WindowResult] = []
        is_sharpes: list[float] = []
        oos_sharpes: list[float] = []

        base_config = BacktestConfig(
            symbol=symbol,
            exchange="walk_forward",
            timeframe="1h",
            initial_equity=initial_equity,
        )

        for i in range(n_windows):
            window_bars = bars[i * window_size: (i + 1) * window_size]
            split_idx = int(len(window_bars) * train_pct)
            in_sample = window_bars[:split_idx]
            out_of_sample = window_bars[split_idx:]

            if len(in_sample) < 5 or len(out_of_sample) < 5:
                logger.warning("walk_forward_window_too_small", window=i + 1)
                continue

            logger.debug(
                "walk_forward_window",
                window=i + 1,
                n_windows=n_windows,
                in_sample_bars=len(in_sample),
                out_of_sample_bars=len(out_of_sample),
            )

            is_engine = BacktestEngine(base_config)
            oos_engine = BacktestEngine(base_config)

            is_result = await is_engine.run(in_sample, strategy_fn)
            oos_result = await oos_engine.run(out_of_sample, strategy_fn)

            is_sharpe = is_result.metrics.sharpe_ratio
            oos_sharpe = oos_result.metrics.sharpe_ratio

            is_sharpes.append(is_sharpe)
            oos_sharpes.append(oos_sharpe)

            window_results.append(WindowResult(
                window_index=i + 1,
                in_sample_sharpe=is_sharpe,
                out_of_sample_sharpe=oos_sharpe,
                in_sample_bars=len(in_sample),
                out_of_sample_bars=len(out_of_sample),
                in_sample_trades=is_result.metrics.total_trades,
                out_of_sample_trades=oos_result.metrics.total_trades,
                in_sample_start=str(in_sample[0].ts.date()),
                in_sample_end=str(in_sample[-1].ts.date()),
                out_of_sample_start=str(out_of_sample[0].ts.date()),
                out_of_sample_end=str(out_of_sample[-1].ts.date()),
            ))

        avg_is = float(np.mean(is_sharpes)) if is_sharpes else 0.0
        avg_oos = float(np.mean(oos_sharpes)) if oos_sharpes else 0.0

        # Degradation ratio: how much worse is OOS vs IS?
        # Ideal = 1.0. Acceptable = < 2.0. Overfit = > 3.0.
        if avg_oos > 0 and avg_is > 0:
            degradation_ratio = round(avg_is / avg_oos, 4)
        elif avg_is > 0 and avg_oos <= 0:
            degradation_ratio = float("inf")  # loses money out-of-sample = completely overfit
        else:
            degradation_ratio = 1.0

        is_robust = avg_oos > 0 and degradation_ratio < 2.0

        # Loud warning for severely overfit strategies
        if degradation_ratio > 3.0:
            print(
                f"\n{'='*60}\n"
                f"  WARNING: STRATEGY IS MASSIVELY OVERFIT\n"
                f"{'='*60}\n"
                f"  Strategy:            {strategy_name}\n"
                f"  In-sample Sharpe:    {avg_is:.2f}\n"
                f"  Out-of-sample Sharpe:{avg_oos:.2f}\n"
                f"  Degradation ratio:   {degradation_ratio:.2f}x\n"
                f"\n"
                f"  The strategy is fitting noise, not signal.\n"
                f"  A degradation > 3.0x means IS performance will NOT\n"
                f"  repeat live. Do NOT deploy this strategy.\n"
                f"{'='*60}\n"
            )

        return WalkForwardResult(
            symbol=symbol,
            strategy_name=strategy_name,
            n_windows=n_windows,
            in_sample_sharpe=round(avg_is, 4),
            out_of_sample_sharpe=round(avg_oos, 4),
            degradation_ratio=degradation_ratio,
            window_results=window_results,
            is_robust=is_robust,
            total_bars=len(bars),
        )
