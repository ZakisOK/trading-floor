"""SkillLoader — load standard operating procedure skills for Trading Floor agents.

Skills live on disk as YAML-frontmatter + markdown files inside
``src/agents/skills/<agent_id>/``. Shared skills live in
``src/agents/skills/_shared/``. Each agent folder also contains a cheap
``SKILL_INDEX.md`` file that can be inlined into a system prompt so the agent
knows which SOPs it owns without paying the token cost to load every body.
"""
from __future__ import annotations

from pathlib import Path

import structlog
from pydantic import BaseModel, ConfigDict, Field

logger = structlog.get_logger()


class Skill(BaseModel):
    """A fully-loaded skill (frontmatter + markdown body)."""

    model_config = ConfigDict(strict=True)

    name: str
    description: str
    triggers: list[str] = Field(default_factory=list)
    requires_tools: list[str] = Field(default_factory=list)
    cost_tokens: int = 0
    body: str
    agent_id: str


def _parse_frontmatter(text: str) -> tuple[dict[str, object], str]:
    """Parse a YAML-style frontmatter block from ``text``.

    We use a tiny hand-rolled parser so the library has no hard YAML dep.
    Supports scalar keys and single-line list syntax ``[a, b, c]`` which is
    sufficient for our skill frontmatter format.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    end_idx: int | None = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_idx = idx
            break
    if end_idx is None:
        return {}, text
    meta: dict[str, object] = {}
    for raw in lines[1:end_idx]:
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        if ":" not in raw:
            continue
        key, _, value = raw.partition(":")
        key = key.strip()
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            if not inner:
                meta[key] = []
            else:
                meta[key] = [item.strip().strip('"').strip("'") for item in inner.split(",")]
        elif value.isdigit() or (value.startswith("-") and value[1:].isdigit()):
            meta[key] = int(value)
        elif value.lower() in {"true", "false"}:
            meta[key] = value.lower() == "true"
        else:
            meta[key] = value.strip('"').strip("'")
    body = "\n".join(lines[end_idx + 1 :]).lstrip("\n")
    return meta, body


class SkillLoader:
    """Loads Trading Floor agent skills from disk.

    Parameters
    ----------
    root:
        Optional override for the skills directory. Defaults to the package
        directory this module lives in.
    """

    SHARED = "_shared"
    INDEX_FILENAME = "SKILL_INDEX.md"

    def __init__(self, root: Path | None = None) -> None:
        self._root: Path = root if root is not None else Path(__file__).resolve().parent

    # ------------------------------------------------------------------ helpers

    def _agent_dir(self, agent_id: str) -> Path:
        return self._root / agent_id

    def _read(self, path: Path) -> str | None:
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            logger.warning("skill_file_missing", path=str(path))
            return None
        except OSError as exc:
            logger.warning("skill_file_unreadable", path=str(path), error=str(exc))
            return None

    def _parse_index(self, agent_id: str) -> list[dict[str, str]]:
        """Parse an agent's ``SKILL_INDEX.md`` into ``[{name, description, triggers}]``.

        Index lines look like::

            - name — one-line trigger summary
        """
        text = self._read(self._agent_dir(agent_id) / self.INDEX_FILENAME)
        if text is None:
            return []
        entries: list[dict[str, str]] = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line.startswith("-"):
                continue
            body = line.lstrip("-").strip()
            if not body:
                continue
            sep = None
            for candidate in (" — ", " - ", ": "):
                if candidate in body:
                    sep = candidate
                    break
            if sep is None:
                entries.append({"name": body, "description": "", "triggers": ""})
                continue
            name, _, desc = body.partition(sep)
            entries.append(
                {
                    "name": name.strip(),
                    "description": desc.strip(),
                    "triggers": "",
                }
            )
        return entries

    # ------------------------------------------------------------------ API

    def list_skills(self, agent_id: str) -> list[dict[str, str]]:
        """Return the cheap index (one entry per SOP) for an agent."""
        return self._parse_index(agent_id)

    def get_system_prompt_index(self, agent_id: str) -> str:
        """Return the raw ``SKILL_INDEX.md`` markdown for embedding in a prompt."""
        text = self._read(self._agent_dir(agent_id) / self.INDEX_FILENAME)
        return text or ""

    def load(self, skill_name: str, agent_id: str | None = None) -> Skill | None:
        """Load a single skill by name. If ``agent_id`` is None, also checks
        the shared skills directory."""
        candidates: list[str] = []
        if agent_id is not None:
            candidates.append(agent_id)
        candidates.append(self.SHARED)
        seen: set[str] = set()
        for owner in candidates:
            if owner in seen:
                continue
            seen.add(owner)
            path = self._agent_dir(owner) / f"{skill_name}.md"
            text = self._read(path)
            if text is None:
                continue
            meta, body = _parse_frontmatter(text)
            try:
                return Skill(
                    name=str(meta.get("name", skill_name)),
                    description=str(meta.get("description", "")),
                    triggers=list(meta.get("triggers") or []),  # type: ignore[arg-type]
                    requires_tools=list(meta.get("requires_tools") or []),  # type: ignore[arg-type]
                    cost_tokens=int(meta.get("cost_tokens", 0) or 0),
                    body=body,
                    agent_id=owner,
                )
            except (TypeError, ValueError) as exc:
                logger.warning(
                    "skill_parse_failed",
                    skill=skill_name,
                    owner=owner,
                    error=str(exc),
                )
                return None
        logger.warning("skill_not_found", skill=skill_name, agent_id=agent_id)
        return None

    def load_many(
        self, skill_names: list[str], agent_id: str | None = None
    ) -> list[Skill]:
        out: list[Skill] = []
        for name in skill_names:
            skill = self.load(name, agent_id=agent_id)
            if skill is not None:
                out.append(skill)
        return out


_skill_loader: SkillLoader | None = None


def get_skill_loader() -> SkillLoader:
    """Module-level singleton accessor."""
    global _skill_loader
    if _skill_loader is None:
        _skill_loader = SkillLoader()
    return _skill_loader


def reset_skill_loader() -> None:
    """Test helper — drop the cached singleton."""
    global _skill_loader
    _skill_loader = None
