"""Agent registry — startup roster + agent_version sanity check (Week 1 / B2).

Every agent that participates in a cycle MUST be registered here with a
non-empty ``agent_version``. Startup calls ``assert_versions()`` and refuses
to boot if any agent lacks one. This is the gate behind T-VERSION-02.

The registry is import-light on purpose: it pulls the agent objects already
constructed by ``src.agents.sage`` rather than building its own. That way we
don't accidentally double-instantiate agents with side effects.
"""
from __future__ import annotations

import structlog

from src.agents.base import BaseAgent
from src.core.versioning import AGENT_VERSION_RE

logger = structlog.get_logger()


def collect_known_agents() -> list[BaseAgent]:
    """Return every BaseAgent instance currently wired into the trading graph.

    Late import so this module can be imported during early startup without
    pulling LangGraph and the full agent stack just to check versions.
    """
    from src.agents import sage as sage_mod

    seen: set[int] = set()
    candidates: list[BaseAgent] = []
    for attr in dir(sage_mod):
        obj = getattr(sage_mod, attr)
        if isinstance(obj, BaseAgent) and id(obj) not in seen:
            seen.add(id(obj))
            candidates.append(obj)
    # Stable ordering by agent_id for deterministic startup logs
    candidates.sort(key=lambda a: a.agent_id)
    return candidates


def assert_versions(agents: list[BaseAgent] | None = None) -> list[BaseAgent]:
    """Raise if any registered agent has a missing or malformed agent_version.

    Returns the validated roster so callers can chain into a startup log.
    """
    roster = agents if agents is not None else collect_known_agents()
    bad: list[tuple[str, str]] = []
    for agent in roster:
        version = getattr(agent, "agent_version", None)
        if not version or not AGENT_VERSION_RE.match(version):
            bad.append((agent.agent_id, str(version)))
    if bad:
        details = ", ".join(f"{a}={v!r}" for a, v in bad)
        raise RuntimeError(
            f"agent_version missing or malformed for: {details}. "
            f"Every agent must call super().__init__(agent_id, name, role, "
            f"prompt_template=..., model_name=...) so a version is computed."
        )
    return roster


def log_roster(agents: list[BaseAgent] | None = None) -> None:
    """Structured log of every agent + version. Run once at startup."""
    roster = assert_versions(agents)
    logger.info(
        "agent_roster_loaded",
        count=len(roster),
        agents=[
            {"agent_id": a.agent_id, "name": a.name, "version": a.agent_version}
            for a in roster
        ],
    )
