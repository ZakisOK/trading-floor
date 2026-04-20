"""OutcomeWriter entry point — drains stream:trade_outcomes.

Run as a long-lived service alongside the episode_writer.

Usage:
    python scripts/run_outcome_writer.py
"""
from __future__ import annotations

import asyncio
import signal
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import structlog

from src.core.database import AsyncSessionLocal
from src.core.redis import get_redis
from src.streams.outcome_writer import OutcomeWriter

logger = structlog.get_logger()


_SHUTDOWN = asyncio.Event()


def _handle_signal(signum, _frame) -> None:  # type: ignore[type-arg]
    logger.info("outcome_writer_shutdown_requested", signal=signum)
    _SHUTDOWN.set()


async def main() -> None:
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    redis = get_redis()
    consumer_name = f"outcome_writer-{socket.gethostname()}"
    writer = OutcomeWriter(
        redis=redis,
        session_factory=AsyncSessionLocal,
        consumer_name=consumer_name,
    )

    logger.info(
        "outcome_writer_starting",
        consumer_name=consumer_name,
        stream="stream:trade_outcomes",
        group="cg:outcome_writer",
    )

    consumer_task = asyncio.create_task(writer.start())
    shutdown_task = asyncio.create_task(_SHUTDOWN.wait())

    done, _pending = await asyncio.wait(
        {consumer_task, shutdown_task},
        return_when=asyncio.FIRST_COMPLETED,
    )

    await writer.stop()
    consumer_task.cancel()
    for t in done:
        if t is consumer_task and t.exception():
            raise t.exception()  # type: ignore[misc]

    logger.info("outcome_writer_stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
