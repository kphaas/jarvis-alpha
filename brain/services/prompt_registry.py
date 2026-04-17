"""Prompt registry — abstracted storage for dream mode prompts.

Current implementation: MarkdownRegistry reads from brain/prompts/dream/*.md
Future (Alpha-3): PostgresRegistry for hot-swappable prompts with versioning.

Usage:
    registry = MarkdownRegistry(root=Path('brain/prompts/dream'))
    planner_prompt = await registry.get('planner', version='v1')
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path

log = logging.getLogger(__name__)


class PromptNotFoundError(Exception):
    """Raised when a prompt is requested but no matching file/row exists."""


class IPromptRegistry(ABC):
    """Abstract base for prompt storage backends."""

    @abstractmethod
    async def get(self, name: str, version: str = "v1") -> str:
        """Return raw prompt text for name@version.

        Raises PromptNotFoundError if missing.
        """
        ...

    @abstractmethod
    async def list_versions(self, name: str) -> list[str]:
        """Return all available versions for a prompt name, newest first."""
        ...


class MarkdownRegistry(IPromptRegistry):
    """Markdown-file-backed registry.

    Expects files under root: {name}_{version}.md
    Example: brain/prompts/dream/planner_v1.md
    """

    def __init__(self, root: Path):
        self._root = Path(root)
        if not self._root.exists():
            raise ValueError(f"Prompt root does not exist: {self._root}")

    async def get(self, name: str, version: str = "v1") -> str:
        fname = f"{name}_{version}.md"
        path = self._root / fname
        if not path.exists():
            raise PromptNotFoundError(f"Prompt not found: {path}")
        content = path.read_text(encoding="utf-8")
        log.debug("prompt_registry loaded %s (%d bytes)", fname, len(content))
        return content

    async def list_versions(self, name: str) -> list[str]:
        pattern = f"{name}_*.md"
        matches = sorted(self._root.glob(pattern), reverse=True)
        versions = []
        for m in matches:
            stem = m.stem
            prefix = f"{name}_"
            if stem.startswith(prefix):
                versions.append(stem[len(prefix) :])
        return versions
