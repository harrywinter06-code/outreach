"""Per-service Playwright storage_state persistence.

Stored at `<root>/<service>.json`. Service names must be slug-safe —
a name containing `/`, `..`, or other path components is rejected at
write time, defeating path-traversal payloads from organism-authored skills."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_SERVICE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class ProfileStore:
    def __init__(self, root: str) -> None:
        self._root = Path(root)

    def _path(self, service: str) -> Path:
        if not _SERVICE_NAME_RE.match(service):
            raise ValueError(f"unsafe service name: {service!r}")
        return self._root / f"{service}.json"

    def save(self, service: str, state: dict[str, Any]) -> None:
        path = self._path(service)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state), encoding="utf-8")

    def load(self, service: str) -> dict[str, Any] | None:
        path = self._path(service)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def exists(self, service: str) -> bool:
        return self._path(service).exists()
