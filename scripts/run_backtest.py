"""
Run a backtest from the command line, with optional walk-forward validation.

Usage examples:
  python scripts/run_backtest.py --symbol XRP/USDT --strategy xrp_momentum
  python scripts/run_backtest.py --symbol BTC/USDT --strategy sma_crossover --walk-forward
  python scripts/run_backtest.py --symbol XRP/USDT --strategy xrp_momentum --walk-forward --windows 6

Supported strategies:
  sma_crossover, rsi_mean_reversion, xrp_momentum,
  gold_safe_haven, commodity_momentum, seasonal_commodity
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta, UTC

import structlog

# Ensure project root is on the path when running from scripts/
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.backtesting.strategies import AVAILABLE_STRATEGIES
from src.backtesting.validation import BacktestValidator
from src.backtesting.walk_forward import WalkForwardValidator

logger = structlog.get_logger()


def _risk_color(level: str) -> str:
    """ANSI color codes for terminal output."""
    return {"HIGH": "\033[91m", "MEDIUM": "\033[93m", "LOW": "\033[92m"}.get(level, "")

RESET = "\033[0m"
BOLD = "\033[1m"


def _make_fake_bars(symbol: str, n_bars: int = 500):
    """
    Generate synthetic OHLCV bars for offline testing when no live data feed is available.
    Uses a random walk to simulate realistic price action.
    Not suitable for real strategy development — for CLI smoke-testing only.
    """
    import random
    from src.data.models.market import OHLCVBar
    from decimal import Decimal

    random.seed(42)
    bars = []
    price = 1.0 if "XRP" in symbol.upper() else 50000.0 if "BTC" in symbol else 2000.0
    ts = datetime.now(UTC) - timedelta(hours=n_bars)

    for _ in range(n_bars):
        change = random.gauss(0, 0.012)
        open_ = price
        close = price * (1 + change)
        high = max(open_, close) * (1 + abs(random.gauss(0, 0.003)))
        low = min(open_, close) * (1 - abs(random.gauss(0, 0.003)))
        volume = random.uniform(1_000_000, 5_000_000)
        bars.append(OHLCVBar(
            symbol=symbol,
            exchange="synthetic",
            timeframe="1h",
            ts=ts,
            open=Decimal(str(round(open_, 6))),
            high=Decimal(str(round(high, 6))),
            low=Decimal(str(round(low, 6))),
            close=Decimal(str(round(close, 6))),
            volume=Decimal(str(round(volume, 2))),
        ))
        price = close
        ts += timedelta(hours=1)

    return bars


async def run_walk_forward(args: argparse.Namespace) -> None:
    """Run walk-forward validation and print a formatted report."""
    strategy_factory = AVAILABLE_STRATEGIES.get(args.strategy)
    if not strategy_factory:
        print(f"Unknown strategy '{args.strategy}'. Available: {', '.join(AVAILABLE_STRATEGIES)}")
        sys.exit(1)

    strategy_fn = strategy_factory()
    strategy_name = getattr(strategy_fn, "__name__", args.strategy)

    print(f"\n{BOLD}Walk-Forward Validation: {strategy_name} on {args.symbol}{RESET}")
    print(f"  Windows:  {args.windows}  |  Train split: 70%  |  Bars: {args.bars}")
    print()

    bars = _make_fake_bars(args.symbol, n_bars=args.bars)

    validator = WalkForwardValidator()
    result = await validator.run(
        symbol=args.symbol,
        strategy_fn=strategy_fn,
        bars=bars,
        n_windows=args.windows,
        train_pct=0.7,
    )

    # Memorization risk check
    mem_validator = BacktestValidator()
    start_date = bars[0].ts.date()
    end_date = bars[-1].ts.date()
    risk = mem_validator.check_memorization_risk(args.symbol, start_date, end_date)
    risk_level = risk["risk_level"]
    color = _risk_color(risk_level)

    # Header metrics
    robust_label = f"\033[92m✓ ROBUST{RESET}" if result.is_robust else f"\033[91m✗ OVERFIT{RESET}"
    deg = result.degradation_ratio
    deg_str = f"∞" if deg == float("inf") else f"{deg:.2f}"

    print(f"  {'In-sample Sharpe:':<28} {result.in_sample_sharpe:.2f}")
    print(f"  {'Out-of-sample Sharpe:':<28} {result.out_of_sample_sharpe:.2f}")
    print(f"  {'Degradation ratio:':<28} {deg_str}  {robust_label}")
    print(f"  {'Memorization risk:':<28} {color}{risk_level}{RESET} ({risk['reason'][:80]}...)")
    print()

    # Per-window breakdown
    print(f"  {'Window':<8} {'IS Sharpe':>12} {'OOS Sharpe':>12} {'IS Trades':>10} {'OOS Trades':>11}")
    print("  " + "-" * 58)
    for w in result.window_results:
        oos_color = "\033[92m" if w.out_of_sample_sharpe > 0 else "\033[91m"
        print(
            f"  {w.window_index:<8} "
            f"{w.in_sample_sharpe:>12.2f} "
            f"{oos_color}{w.out_of_sample_sharpe:>12.2f}{RESET} "
            f"{w.in_sample_trades:>10} "
            f"{w.out_of_sample_trades:>11}"
        )

    print()
    if result.is_robust:
        print(f"  {BOLD}Verdict: Strategy is ROBUST across all walk-forward windows.{RESET}")
        print(f"  Degradation ratio {deg_str}x is within the acceptable threshold (< 2.0x).")
    else:
        print(f"  {BOLD}Verdict: Strategy is NOT ROBUST.{RESET}")
        if result.out_of_sample_sharpe <= 0:
            print("  Out-of-sample Sharpe is negative — strategy loses money on unseen data.")
        else:
            print(f"  Degradation ratio {deg_str}x exceeds the 2.0x robustness threshold.")
    print()


async def run_single(args: argparse.Namespace) -> None:
    """Run a single backtest and print the result summary."""
    from src.backtesting.engine import BacktestEngine, BacktestConfig

    strategy_factory = AVAILABLE_STRATEGIES.get(args.strategy)
    if not strategy_factory:
        print(f"Unknown strategy '{args.strategy}'. Available: {', '.join(AVAILABLE_STRATEGIES)}")
        sys.exit(1)

    strategy_fn = strategy_factory()
    bars = _make_fake_bars(args.symbol, n_bars=args.bars)

    config = BacktestConfig(
        symbol=args.symbol,
        exchange="synthetic",
        timeframe="1h",
        initial_equity=10000.0,
    )
    engine = BacktestEngine(config)
    result = await engine.run(bars, strategy_fn)

    m = result.metrics
    risk_color = _risk_color(result.memorization_risk)
    adj_sharpe = result.validity_flags.get("adjusted_sharpe", m.sharpe_ratio)

    print(f"\n{BOLD}Backtest Result: {args.strategy} on {args.symbol}{RESET}")
    print(f"  {'Total Return:':<28} {m.total_return_pct:+.2f}%")
    print(f"  {'CAGR:':<28} {m.cagr:.2f}%")
    print(f"  {'Sharpe Ratio (raw):':<28} {m.sharpe_ratio:.2f}")
    print(f"  {'Sharpe Ratio (adjusted):':<28} {adj_sharpe:.2f}")
    print(f"  {'Max Drawdown:':<28} {m.max_drawdown_pct:.2f}%")
    print(f"  {'Win Rate:':<28} {m.win_rate:.1f}%")
    print(f"  {'Total Trades:':<28} {m.total_trades}")
    print(f"  {'Memorization Risk:':<28} {risk_color}{result.memorization_risk}{RESET}")

    warnings = result.validity_flags.get("warnings", [])
    if warnings:
        print()
        for w in warnings:
            print(f"  ⚠  {w}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Trading Floor backtester with memorization safeguards",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--symbol", default="XRP/USDT", help="Trading symbol (default: XRP/USDT)")
    parser.add_argument(
        "--strategy", default="xrp_momentum",
        choices=list(AVAILABLE_STRATEGIES.keys()),
        help="Strategy to backtest",
    )
    parser.add_argument("--walk-forward", action="store_true", help="Run walk-forward validation")
    parser.add_argument("--windows", type=int, default=4, help="Number of walk-forward windows (default: 4)")
    parser.add_argument("--bars", type=int, default=500, help="Number of synthetic bars to generate (default: 500)")

    args = parser.parse_args()

    if args.walk_forward:
        asyncio.run(run_walk_forward(args))
    else:
        asyncio.run(run_single(args))


if __name__ == "__main__":
    main()
