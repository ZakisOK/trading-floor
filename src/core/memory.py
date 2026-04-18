"""Firm memory — thin async wrapper around a Graphiti REST service.

Requires: httpx (already listed in project pyproject.toml).

Graphiti is treated as a remote service. Each agent has a private group (the
``group_ids`` list on episodes and searches is scoped to ``[agent_id]``).
Firm-wide knowledge is reached by querying without ``group_ids``.

The module is deliberately resilient: if Graphiti is unreachable, calls log a
warning via structlog and return empty / no-op results so agents never crash.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import structlog

from src.core.config import settings

logger = structlog.get_logger()


class FirmMemory:
    """Async client for the Graphiti REST service.

    Parameters
    ----------
    base_url:
        Root URL of the Graphiti HTTP service (e.g. ``http://graphiti:8000``).
    messages_path / search_path / facts_path:
        Override paths if the deployed Graphiti build exposes non-default
        endpoints.
    timeout:
        Request timeout in seconds.
    """

    def __init__(
        self,
        base_url: str,
        *,
        messages_path: str = "/messages",
        search_path: str = "/search",
        facts_path: str = "/facts",
        timeout: float = 10.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._messages_path = messages_path
        self._search_path = search_path
        self._facts_path = facts_path
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=timeout)

    async def add_episode(
        self,
        *,
        agent_id: str,
        episode_type: str,
        content: str,
        reference_time: datetime | None = None,
        source_description: str = "",
    ) -> dict[str, Any]:
        """Record an episode (observation / reflection / signal / trade) for an agent.

        Episodes are partitioned per-agent via ``group_ids=[agent_id]`` so each
        agent has a private store. Cross-agent firm knowledge is written under
        the special group ``firm``.
        """
        ts = (reference_time or datetime.now(UTC)).isoformat()
        payload: dict[str, Any] = {
            "group_id": agent_id,
            "messages": [
                {
                    "name": episode_type,
                    "content": content,
                    "role_type": "user",
                    "role": agent_id,
                    "timestamp": ts,
                    "source_description": source_description,
                }
            ],
        }
        try:
            resp = await self._client.post(self._messages_path, json=payload)
            resp.raise_for_status()
            return resp.json() if resp.content else {"ok": True}
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning(
                "firm_memory_add_episode_failed",
                agent_id=agent_id,
                episode_type=episode_type,
                error=str(exc),
            )
            return {"ok": False, "error": str(exc)}

    async def search(
        self,
        *,
        query: str,
        agent_id: str | None = None,
        limit: int = 10,
        group_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Search memory. Passing neither ``agent_id`` nor ``group_ids`` spans
        the whole firm (public knowledge)."""
        effective_groups: list[str] | None = group_ids
        if effective_groups is None and agent_id is not None:
            effective_groups = [agent_id]
        payload: dict[str, Any] = {"query": query, "max_facts": limit}
        if effective_groups is not None:
            payload["group_ids"] = effective_groups
        try:
            resp = await self._client.post(self._search_path, json=payload)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning(
                "firm_memory_search_failed",
                query=query,
                error=str(exc),
            )
            return []
        # Graphiti commonly returns {"facts": [...]} or {"results": [...]}; be flexible.
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("facts", "results", "edges", "nodes"):
                val = data.get(key)
                if isinstance(val, list):
                    return val
        return []

    async def add_fact(
        self,
        *,
        agent_id: str,
        subject: str,
        predicate: str,
        object_: str,
        confidence: float = 1.0,
    ) -> dict[str, Any]:
        """Write a structured subject-predicate-object fact into Graphiti."""
        payload: dict[str, Any] = {
            "group_id": agent_id,
            "subject": subject,
            "predicate": predicate,
            "object": object_,
            "confidence": confidence,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        try:
            resp = await self._client.post(self._facts_path, json=payload)
            resp.raise_for_status()
            return resp.json() if resp.content else {"ok": True}
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning(
                "firm_memory_add_fact_failed",
                agent_id=agent_id,
                subject=subject,
                error=str(exc),
            )
            return {"ok": False, "error": str(exc)}

    async def close(self) -> None:
        await self._client.aclose()


_firm_memory: FirmMemory | None = None


def get_memory() -> FirmMemory:
    """Lazy singleton accessor for the firm memory client."""
    global _firm_memory
    if _firm_memory is None:
        _firm_memory = FirmMemory(settings.graphiti_url)
    return _firm_memory


def reset_memory() -> None:
    """Test helper — drops the cached singleton so the next ``get_memory()``
    call builds a fresh client (useful for monkeypatching URL/transport)."""
    global _firm_memory
    _firm_memory = None
