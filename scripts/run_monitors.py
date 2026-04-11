"""
Monitor entry point — runs position_monitor (5s), risk_monitor (30s),
and trade_desk concurrently.

Usage:
    python scripts/run_monitors.py

Keep this running alongside the paper trading loop. The monitors fire exits
immediately when a stop or target is hit — they do NOT wait for the agent cycle.
TradeDeskAgent listens to stream:trade_desk:inbox and drives execution for
every conviction packet Nova publishes.
"""
from __future__ import annotations

import asyncio
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import structlog

from src.execution.position_monitor import run as run_position_monitor
from src.execution.risk_monitor import run as run_risk_monitor
from src.execution.trade_desk import trade_desk

logger = structlog.get_logger()


def _handle_signal(signum, _frame) -> None:  # type: ignore[type-arg]
    logger.info("monitors_shutdown_requested", signal=signum)
    for task in asyncio.all_tasks():
        task.cancel()


async def main() -> None:
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    logger.info("monitors_starting", position_interval_s=5, risk_interval_s=30)
    try:
        await asyncio.gather(
            run_position_monitor(),   # sweeps every 5s — fires exits immediately
            run_risk_monitor(),       # sweeps every 30s — enforces daily loss limit
            trade_desk.run(),         # Desk 2 — processes Nova conviction packets
        )
    except asyncio.CancelledError:
        logger.info("monitors_stopped")


if __name__ == "__main__":
    asyncio.run(main())
