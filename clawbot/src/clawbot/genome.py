"""
SOUL.md genome helpers — read, write, and mutate agent genomes.
Writes use temp-file-then-rename for atomicity; concurrent writers from
different containers won't corrupt the file mid-write.
"""
import os
import re
import tempfile
import time
from pathlib import Path


_MUTABLE_MARKER = "## MUTABLE"
_SECTION_RE = re.compile(r"^#+\s+", re.MULTILINE)

# Windows-specific: os.replace can fail with PermissionError if another process
# has the target file open for reading. The executive cycle reads SOUL.md every
# 10 minutes; evolution writes it. Without retry, an unlucky collision crashes
# the scheduler. Bounded retry with backoff makes the race observably rare.
_WRITE_RETRY_ATTEMPTS = 5
_WRITE_RETRY_DELAY_S = 0.1


def read_soul(soul_path: Path) -> str:
    return soul_path.read_text(encoding="utf-8")


def write_soul(soul_path: Path, content: str) -> None:
    """Atomic write via temp file. Retries os.replace on Windows PermissionError."""
    dir_ = soul_path.parent
    fd, tmp_path = tempfile.mkstemp(dir=dir_, prefix=".soul_tmp_", suffix=".md")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        last_exc: Exception | None = None
        for attempt in range(_WRITE_RETRY_ATTEMPTS):
            try:
                os.replace(tmp_path, soul_path)
                return
            except PermissionError as exc:
                last_exc = exc
                time.sleep(_WRITE_RETRY_DELAY_S * (attempt + 1))
        # All retries exhausted
        raise last_exc if last_exc else RuntimeError("write_soul exhausted retries with no error")
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def extract_mutable(soul_content: str) -> str:
    """
    Return everything from the first ## MUTABLE section to end of file.
    Raises ValueError if no MUTABLE section exists (immutable-only SOUL).
    """
    idx = soul_content.find(_MUTABLE_MARKER)
    if idx == -1:
        raise ValueError("SOUL.md has no ## MUTABLE section — cannot evolve")
    return soul_content[idx:]


def replace_mutable(soul_content: str, new_mutable: str) -> str:
    """
    Replace the mutable section of a SOUL.md with new content.
    The immutable header is preserved exactly.
    """
    idx = soul_content.find(_MUTABLE_MARKER)
    if idx == -1:
        raise ValueError("SOUL.md has no ## MUTABLE section")
    immutable_part = soul_content[:idx]
    return immutable_part + new_mutable


def section_names(soul_content: str) -> list[str]:
    """Return all ## section headers found in the SOUL.md."""
    return [m.string[m.start():].split("\n")[0].lstrip("#").strip()
            for m in _SECTION_RE.finditer(soul_content)]


def mutate_soul(
    soul_path: Path,
    mutation: str,
) -> None:
    """
    Apply a mutation string (LLM-generated new mutable section) to a SOUL.md.
    The mutation replaces the existing ## MUTABLE section onward.
    """
    current = read_soul(soul_path)
    updated = replace_mutable(current, mutation)
    write_soul(soul_path, updated)
