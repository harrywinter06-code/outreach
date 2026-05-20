"""Pytest configuration.

Sets INTERNSHIP_HUNTER_DB_PATH before any project module is imported so
tests target an isolated SQLite file rather than the real applications.db.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

# Must run before any `import tracker` (and therefore before any `import config`).
_TMP_DIR = Path(tempfile.mkdtemp(prefix="ihunter-test-"))
os.environ["INTERNSHIP_HUNTER_DB_PATH"] = str(_TMP_DIR / "test.db")
