"""Agent version + git sha helpers (Week 1 / B2).

`agent_version` format: ``{git_sha_8}:{model_name}:{prompt_hash_8}``.

Stored on every episode. Replay queries filter by version explicitly. If an
agent ships without a version, startup fails — see registry.assert_versions().

The format is enforced by:
- The DB CHECK constraint on agent_episodes.agent_version
- The AGENT_VERSION_RE regex below (used in tests + assertion helpers)
"""
from __future__ import annotations

import hashlib
import re
import subprocess
from functools import lru_cache
from pathlib import Path

AGENT_VERSION_RE = re.compile(r"^[a-f0-9]{8}:[a-zA-Z0-9_.-]+:[a-f0-9]{8}$")

# Fallback when git isn't available (CI, container, stripped install).
# Eight zeros is a valid sha shape; downstream queries can detect "no git"
# rows by filtering on this prefix.
_NO_GIT_SHA = "00000000"


@lru_cache(maxsize=1)
def get_current_git_sha() -> str:
    """Return the first 8 chars of the HEAD commit, or '00000000' if unavailable.

    Cached because the answer doesn't change for the lifetime of the process
    (a redeploy creates a new process).
    """
    repo_root = Path(__file__).resolve().parent.parent.parent
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return _NO_GIT_SHA
    if out.returncode != 0:
        return _NO_GIT_SHA
    sha = (out.stdout or "").strip()[:8]
    if len(sha) != 8 or not all(c in "0123456789abcdef" for c in sha):
        return _NO_GIT_SHA
    return sha


def _hash_prompt(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:8]


def _normalize_model_name(model_name: str) -> str:
    """Squash chars that would break the agent_version regex.

    The CHECK constraint allows ``[a-zA-Z0-9_.-]``. Anything else collapses to
    a single dash so the version still validates.
    """
    cleaned = re.sub(r"[^a-zA-Z0-9_.-]+", "-", model_name).strip("-")
    return cleaned or "unknown"


def compute_agent_version(model_name: str, prompt_template: str) -> str:
    """Compose the canonical agent_version string for an agent at init time.

    Inputs:
        model_name: e.g. ``"claude-opus-4-7"``. Normalized to fit the regex.
        prompt_template: the agent's system prompt (or any stable identifier
            for behavior). Whitespace differences DO change the hash — this is
            on purpose so prompt edits show up as a new version.

    Returns:
        ``"<git_sha_8>:<model>:<prompt_hash_8>"``
    """
    sha = get_current_git_sha()
    model = _normalize_model_name(model_name)
    prompt_hash = _hash_prompt(prompt_template)
    version = f"{sha}:{model}:{prompt_hash}"
    if not AGENT_VERSION_RE.match(version):
        raise ValueError(
            f"computed agent_version {version!r} does not match "
            f"required format {AGENT_VERSION_RE.pattern!r}"
        )
    return version
