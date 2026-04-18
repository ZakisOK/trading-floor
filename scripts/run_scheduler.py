"""Docker entrypoint for the scheduler service."""
from __future__ import annotations

import asyncio

from src.schedulers.cycle_runner import main


if __name__ == "__main__":
    asyncio.run(main())
