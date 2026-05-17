"""Background writer that keeps the brain's skill catalog memory up to date.

On every poll interval, compares the current set of registered skill names
against the last snapshot. If anything changed, writes a new catalog memory
so that the brain's existing recall step surfaces it to executives.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class SkillCatalogWriter:
    """Watches a SkillRegistry and writes a catalog memory to the brain on change.

    Args:
        registry: A SkillRegistry instance (must expose list_names() and get_meta()).
        brain: A CompanyBrain instance (must expose write(text, kind, metadata)).
        poll_interval_s: How often to check for registry changes.
    """

    def __init__(
        self,
        registry: Any,
        brain: Any,
        poll_interval_s: float = 30.0,
    ) -> None:
        self._registry = registry
        self._brain = brain
        self._poll_interval_s = poll_interval_s
        self._last_names: frozenset[str] = frozenset()

    async def write_once(self) -> None:
        """Check for registry changes and write a catalog memory if needed."""
        current_names = frozenset(self._registry.list_names())
        if current_names == self._last_names:
            return
        self._last_names = current_names

        lines = ["Available skills catalog\n"]
        for name in sorted(current_names):
            meta = self._registry.get_meta(name)
            desc = meta.description if meta else ""
            lines.append(f"- {name}: {desc}")
        catalog_text = "\n".join(lines)

        try:
            await self._brain.write(
                catalog_text,
                "skills_catalog",
                {"count": len(current_names), "author": "skill_catalog_writer"},
            )
            logger.info(
                "skill catalog written to brain: %d skills", len(current_names)
            )
        except Exception as exc:
            logger.error("SkillCatalogWriter: brain.write failed: %s", exc)

    async def run_loop(self) -> None:
        """Poll forever, writing the catalog whenever the skill set changes."""
        while True:
            await self.write_once()
            await asyncio.sleep(self._poll_interval_s)
