"""BaseAgent abstract class — stub for Phase 0."""
from abc import ABC, abstractmethod
from typing import Any


class BaseAgent(ABC):
    """All Trading Floor agents extend this class."""

    name: str = "base"

    @abstractmethod
    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        """Execute the agent's main logic and return updated state."""
        ...
