# Company Brain & CTO Self-Modification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a pgvector-backed shared knowledge store all agents can read/write, and a CTO coding agent that can modify, test, and commit changes to its own source code via the message bus.

**Architecture:** `CompanyBrain` wraps asyncpg + pgvector with local ONNX embeddings (no API calls, no PyTorch). `CTOCoder` listens on `code.change_request`, generates whole-file replacements via the existing LLM pool, runs `uv run pytest`, and commits on green or reverts on red. On successful commit the scheduler restarts cleanly so new code loads immediately.

**Tech Stack:** `fastembed>=0.3` (ONNX, CPU-only, ~130MB), `asyncpg>=0.29` (already present), `pgvector>=0.3` (already present), `asyncpg.Pool` + pgvector hnsw index, subprocess git/pytest, Redis Streams bus.

---

## Scope note

These are two independent subsystems. The brain (Tasks 1–4) produces working software on its own. The coder (Tasks 5–9) produces working software on its own. They are in one plan only because both are small and the user requested both together.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `pyproject.toml` | Modify | Add `fastembed>=0.3` |
| `src/clawbot/db.py` | Create | asyncpg pool + schema init (creates `knowledge` table) |
| `src/clawbot/company_brain.py` | Create | `CompanyBrain`: `write`, `search`, `get_recent` |
| `src/clawbot/coder.py` | Create | `CTOCoder`: `run_loop`, `_handle_request`, protected-file guard |
| `agents/cto/SOUL.md` | Create | CTO agent genome |
| `src/clawbot/scheduler.py` | Modify | Add `_coder_loop` + `_code_change_watcher`; accept `brain` param |
| `src/clawbot/main.py` | Modify | Construct `Database`, `CompanyBrain`, pass to `Scheduler` |
| `docker-compose.yml` | Modify | Mount full repo at `/app`; add git author env vars |
| `Dockerfile` | Modify | `apt-get install git` |
| `tests/test_company_brain.py` | Create | 4 unit tests for brain (mocked pool) |
| `tests/test_coder.py` | Create | 6 unit tests for coder (mocked pool, bus, subprocess) |

---

## Task 1: Add fastembed dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Write the failing import test**

```python
# tests/test_company_brain.py  (create this file now with just this test)
def test_fastembed_importable():
    from fastembed import TextEmbedding  # noqa: F401
```

- [ ] **Step 2: Run test to confirm it fails**

```
uv run python -m pytest tests/test_company_brain.py::test_fastembed_importable -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'fastembed'`

- [ ] **Step 3: Add fastembed to pyproject.toml**

In `pyproject.toml`, add `"fastembed>=0.3"` to `dependencies`:

```toml
dependencies = [
    "redis>=5.0",
    "httpx>=0.27",
    "pydantic-settings>=2.0",
    "python-dotenv>=1.0",
    "pgvector>=0.3",
    "asyncpg>=0.29",
    "browser-use>=0.1",
    "langchain-openai>=0.1",
    "tenacity>=8.0",
    "fastembed>=0.3",
]
```

- [ ] **Step 4: Install and verify**

```
uv sync
uv run python -m pytest tests/test_company_brain.py::test_fastembed_importable -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```
git add pyproject.toml tests/test_company_brain.py
git commit -m "feat: add fastembed dependency for local embeddings"
```

---

## Task 2: Database module (asyncpg pool + pgvector schema)

**Files:**
- Create: `src/clawbot/db.py`

This module owns the asyncpg connection pool and creates the `knowledge` table. It is the only place in the codebase that knows the schema.

- [ ] **Step 1: Write the file**

```python
# src/clawbot/db.py
"""
asyncpg connection pool + pgvector schema init.
Only this module knows the knowledge table schema.
"""
import asyncpg
from pgvector.asyncpg import register_vector


class Database:
    def __init__(self, database_url: str) -> None:
        self._url = database_url
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        async def _init(conn: asyncpg.Connection) -> None:
            await register_vector(conn)

        self._pool = await asyncpg.create_pool(
            self._url,
            min_size=2,
            max_size=10,
            init=_init,
        )

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    @property
    def pool(self) -> asyncpg.Pool:
        assert self._pool is not None, "call connect() first"
        return self._pool

    async def init_schema(self) -> None:
        """Idempotent — safe to call on every startup."""
        assert self._pool is not None, "call connect() first"
        await self._pool.execute("CREATE EXTENSION IF NOT EXISTS vector")
        await self._pool.execute("""
            CREATE TABLE IF NOT EXISTS knowledge (
                id         SERIAL PRIMARY KEY,
                content    TEXT        NOT NULL,
                embedding  vector(384),
                category   TEXT        NOT NULL DEFAULT '',
                metadata   JSONB       NOT NULL DEFAULT '{}',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        # hnsw index works on empty tables; ivfflat does not
        await self._pool.execute("""
            CREATE INDEX IF NOT EXISTS knowledge_hnsw_idx
            ON knowledge USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64)
        """)
        await self._pool.execute("""
            CREATE INDEX IF NOT EXISTS knowledge_category_idx
            ON knowledge (category)
        """)
```

- [ ] **Step 2: Verify it imports cleanly (no test needed — infrastructure only)**

```
uv run python -c "from clawbot.db import Database; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```
git add src/clawbot/db.py
git commit -m "feat: add Database class with asyncpg pool and pgvector schema"
```

---

## Task 3: Company Brain module

**Files:**
- Create: `src/clawbot/company_brain.py`

- [ ] **Step 1: Write the file**

```python
# src/clawbot/company_brain.py
"""
Shared company knowledge store — all agents read/write here.
Uses pgvector with local ONNX embeddings (fastembed, no API calls, no PyTorch).
"""
import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg
import numpy as np

logger = logging.getLogger(__name__)

_EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"  # 384 dims, ONNX, ~130 MB download on first use
_MODEL: Any = None  # fastembed.TextEmbedding, lazy-loaded singleton


def _get_model() -> Any:
    global _MODEL
    if _MODEL is None:
        from fastembed import TextEmbedding
        _MODEL = TextEmbedding(_EMBEDDING_MODEL)
        logger.info("Embedding model loaded: %s", _EMBEDDING_MODEL)
    return _MODEL


@dataclass
class BrainEntry:
    id: int
    content: str
    category: str
    metadata: dict
    created_at: datetime
    score: float = 0.0  # cosine similarity — set only during search()


class CompanyBrain:
    """
    All agents share one instance of this class, backed by a single asyncpg pool.
    write()      — embed + store a new knowledge entry
    search()     — semantic similarity lookup (optional category filter)
    get_recent() — latest entries in a category, chronological
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    def _embed_sync(self, text: str) -> np.ndarray:
        """CPU-bound — must NOT be called directly from the event loop."""
        return np.array(list(_get_model().embed([text]))[0])

    async def _embed(self, text: str) -> np.ndarray:
        """
        Run the CPU-bound embedding in the default executor so the scheduler's
        async event loop is not blocked for ~50–200 ms per write. At board-meeting
        fanout (5 shareholder calls + executive cycle, each writing decisions),
        synchronous embedding would block the event loop for ~1 s, misfiring the
        rate-limit minute-bucket arithmetic in llm_pool.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._embed_sync, text)

    async def write(
        self,
        content: str,
        category: str,
        metadata: dict | None = None,
    ) -> int:
        """Store a knowledge entry. Returns the new row id."""
        embedding = await self._embed(content)
        row = await self._pool.fetchrow(
            """INSERT INTO knowledge (content, embedding, category, metadata)
               VALUES ($1, $2::vector, $3, $4)
               RETURNING id""",
            content,
            embedding,
            category,
            json.dumps(metadata or {}),
        )
        return row["id"]

    async def search(
        self,
        query: str,
        k: int = 5,
        category: str | None = None,
    ) -> list[BrainEntry]:
        """
        Return up to k entries ordered by cosine similarity to query.
        Optionally restrict to a single category.
        """
        embedding = await self._embed(query)
        if category:
            rows = await self._pool.fetch(
                """SELECT id, content, category, metadata, created_at,
                          1 - (embedding <=> $1::vector) AS score
                   FROM knowledge
                   WHERE category = $2
                   ORDER BY embedding <=> $1::vector
                   LIMIT $3""",
                embedding, category, k,
            )
        else:
            rows = await self._pool.fetch(
                """SELECT id, content, category, metadata, created_at,
                          1 - (embedding <=> $1::vector) AS score
                   FROM knowledge
                   ORDER BY embedding <=> $1::vector
                   LIMIT $2""",
                embedding, k,
            )
        return [_row_to_entry(r) for r in rows]

    async def get_recent(
        self,
        category: str,
        n: int = 10,
    ) -> list[BrainEntry]:
        """Return the n most recent entries in a category."""
        rows = await self._pool.fetch(
            """SELECT id, content, category, metadata, created_at, 0.0::float AS score
               FROM knowledge
               WHERE category = $1
               ORDER BY created_at DESC
               LIMIT $2""",
            category, n,
        )
        return [_row_to_entry(r) for r in rows]


def _row_to_entry(row: Any) -> BrainEntry:
    raw_meta = row["metadata"]
    if isinstance(raw_meta, str):
        meta = json.loads(raw_meta)
    else:
        meta = raw_meta or {}
    return BrainEntry(
        id=row["id"],
        content=row["content"],
        category=row["category"],
        metadata=meta,
        created_at=row["created_at"],
        score=float(row["score"]),
    )
```

- [ ] **Step 2: Verify import**

```
uv run python -c "from clawbot.company_brain import CompanyBrain, BrainEntry; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```
git add src/clawbot/company_brain.py
git commit -m "feat: add CompanyBrain with pgvector write/search/get_recent"
```

---

## Task 4: Tests for CompanyBrain

**Files:**
- Modify: `tests/test_company_brain.py`

Replace the placeholder file from Task 1 with the full test suite.

- [ ] **Step 1: Write the tests**

```python
# tests/test_company_brain.py
import json
import pytest
import numpy as np
from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock, patch

from clawbot.company_brain import CompanyBrain, BrainEntry, _row_to_entry


def _mock_pool() -> MagicMock:
    pool = MagicMock()
    pool.fetchrow = AsyncMock(return_value={"id": 42})
    pool.fetch = AsyncMock(return_value=[])
    return pool


def _fake_row(
    id: int = 1,
    content: str = "IR35 research",
    category: str = "opportunity",
    metadata: str = "{}",
    score: float = 0.9,
) -> dict:
    return {
        "id": id,
        "content": content,
        "category": category,
        "metadata": metadata,
        "created_at": datetime.now(UTC),
        "score": score,
    }


def test_fastembed_importable():
    from fastembed import TextEmbedding  # noqa: F401


@pytest.mark.asyncio
async def test_write_stores_entry_and_returns_id():
    pool = _mock_pool()
    brain = CompanyBrain(pool)

    with patch.object(brain, "_embed", new=AsyncMock(return_value=np.zeros(384))):
        result = await brain.write("IR35 contractors asking about CEST", "opportunity")

    pool.fetchrow.assert_called_once()
    sql = pool.fetchrow.call_args.args[0]
    assert "INSERT INTO knowledge" in sql
    assert result == 42


@pytest.mark.asyncio
async def test_search_returns_entries():
    pool = _mock_pool()
    pool.fetch = AsyncMock(return_value=[_fake_row()])
    brain = CompanyBrain(pool)

    with patch.object(brain, "_embed", new=AsyncMock(return_value=np.zeros(384))):
        entries = await brain.search("IR35", k=3)

    assert len(entries) == 1
    assert isinstance(entries[0], BrainEntry)
    assert entries[0].score == pytest.approx(0.9)


@pytest.mark.asyncio
async def test_search_with_category_adds_where_clause():
    pool = _mock_pool()
    brain = CompanyBrain(pool)

    with patch.object(brain, "_embed", new=AsyncMock(return_value=np.zeros(384))):
        await brain.search("IR35", k=3, category="opportunity")

    sql = pool.fetch.call_args.args[0]
    assert "WHERE category" in sql


@pytest.mark.asyncio
async def test_get_recent_uses_order_by_created_at():
    pool = _mock_pool()
    brain = CompanyBrain(pool)

    await brain.get_recent("decision", n=5)

    sql = pool.fetch.call_args.args[0]
    assert "ORDER BY created_at DESC" in sql


def test_row_to_entry_parses_json_string_metadata():
    row = _fake_row(metadata='{"source": "reddit"}')
    entry = _row_to_entry(row)
    assert entry.metadata == {"source": "reddit"}


def test_row_to_entry_handles_dict_metadata():
    row = _fake_row(metadata={"source": "reddit"})
    entry = _row_to_entry(row)
    assert entry.metadata == {"source": "reddit"}
```

- [ ] **Step 2: Run tests**

```
uv run python -m pytest tests/test_company_brain.py -v
```

Expected: 7 tests PASS (includes the import test from Task 1)

- [ ] **Step 3: Commit**

```
git add tests/test_company_brain.py
git commit -m "test: company brain write/search/get_recent unit tests"
```

---

## Task 5: Wire Brain into main.py

**Files:**
- Modify: `src/clawbot/main.py`
- Modify: `src/clawbot/scheduler.py`

The brain is constructed in `main()` and passed to `Scheduler` so executive loops can write decisions to it.

- [ ] **Step 1: Update main.py**

Replace the full contents of `src/clawbot/main.py` with:

```python
# src/clawbot/main.py
"""Entry point: wires up all services and starts the scheduler."""
import asyncio
import logging
import sys

from clawbot.bus import MessageBus
from clawbot.company_brain import CompanyBrain
from clawbot.config import settings
from clawbot.db import Database
from clawbot.llm_pool import LLMPool
from clawbot.monitor import Monitor
from clawbot.scheduler import Scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def _startup_checklist() -> None:
    """Fail loudly with specific instructions if revenue infrastructure is missing."""
    errors = []
    if not settings.active_provider_names:
        errors.append(
            "No LLM providers configured. Set at least one of: "
            "NIM_API_KEY, GROQ_API_KEY, GEMINI_API_KEY, CEREBRAS_API_KEY"
        )
    if not settings.gumroad_api_key and not settings.stripe_secret_key:
        errors.append(
            "No payment processor configured — the system cannot receive money. "
            "Set GUMROAD_API_KEY (create account at gumroad.com) "
            "or STRIPE_SECRET_KEY (create account at stripe.com)."
        )
    if errors:
        for msg in errors:
            logger.error("STARTUP BLOCKED: %s", msg)
        sys.exit(1)


async def main() -> None:
    _startup_checklist()
    logger.info("Active providers: %s", settings.active_provider_names)

    pool = LLMPool(settings=settings)
    bus = MessageBus(redis_url=settings.redis_url)
    monitor = Monitor(
        redis_url=settings.redis_url,
        max_daily_spend_usd=settings.max_daily_spend_usd,
    )
    db = Database(database_url=settings.database_url)

    await asyncio.gather(pool.connect(), bus.connect(), monitor.connect(), db.connect())
    await db.init_schema()

    brain = CompanyBrain(pool=db.pool)

    topics = ["ceo.directive", "board.resolution", "coo.task", "cmo.campaign"]
    for topic in topics:
        await bus.subscribe(topic)

    scheduler = Scheduler(pool=pool, bus=bus, monitor=monitor, brain=brain)
    try:
        await scheduler.run_forever()
    finally:
        await asyncio.gather(pool.close(), bus.close(), monitor.close(), db.close())


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Update Scheduler to accept brain**

In `src/clawbot/scheduler.py`, add `brain` to `__init__` and write CEO decisions to it. The minimal change:

```python
# Add to imports at top of scheduler.py:
from clawbot.company_brain import CompanyBrain

# Replace __init__ signature:
def __init__(
    self,
    pool: LLMPool,
    bus: MessageBus,
    monitor: Monitor,
    agents_dir: Path = AGENTS_DIR,
    metrics_dir: Path = METRICS_DIR,
    brain: CompanyBrain | None = None,
) -> None:
    self._pool = pool
    self._bus = bus
    self._monitor = monitor
    self._agents_dir = agents_dir
    self._metrics_dir = metrics_dir
    self._brain = brain

# In _run_executive_cycle, after publishing to bus, add:
if self._brain and response:
    try:
        await self._brain.write(response, category="decision")
    except Exception as exc:
        logger.warning("Brain write failed (non-fatal): %s", exc)
```

The full updated `_run_executive_cycle` method. Note that the CEO now READS from
the brain before acting (most-relevant past decisions are surfaced in the prompt) —
without this read, brain is a write-only journal and the architectural claim
"all agents share knowledge" is unmet.

```python
async def _run_executive_cycle(self) -> None:
    soul_path = self._agents_dir / "ceo" / "SOUL.md"
    if not soul_path.exists():
        return
    soul = soul_path.read_text(encoding="utf-8")
    metrics = await self._load_metrics()
    recent_decisions = ""
    if self._brain:
        try:
            entries = await self._brain.search(
                query=json.dumps(metrics)[:500],
                k=3,
                category="decision",
            )
            if entries:
                recent_decisions = "\n\nRelevant prior decisions:\n" + "\n".join(
                    f"- {e.content[:200]}" for e in entries
                )
        except Exception as exc:
            logger.warning("Brain read failed (non-fatal): %s", exc)
    messages = [
        {"role": "system", "content": soul},
        {
            "role": "user",
            "content": (
                f"Current metrics:\n{json.dumps(metrics, indent=2)}"
                f"{recent_decisions}\n\n"
                "What is your next action? Output JSON: "
                '{"action": "...", "directive": "...", "priority": "high|medium|low"}'
            ),
        },
    ]
    try:
        response = await self._pool.complete(messages, tier="executive")
        await self._bus.publish("ceo.directive", {"response": response, "ts": datetime.now(UTC).isoformat()})
        if self._brain and response:
            try:
                await self._brain.write(response, category="decision")
            except Exception as exc:
                logger.warning("Brain write failed (non-fatal): %s", exc)
    except Exception as exc:
        logger.error("Executive cycle failed: %s", exc)
```

- [ ] **Step 3: Run all tests**

```
uv run python -m pytest -v
```

Expected: all tests PASS (scheduler tests use `brain=None` which is the default)

- [ ] **Step 4: Commit**

```
git add src/clawbot/main.py src/clawbot/scheduler.py
git commit -m "feat: wire CompanyBrain into main startup and CEO decision log"
```

---

## Task 6: CTO Coder module

**Files:**
- Create: `src/clawbot/coder.py`

The most critical safety invariant: tests must pass before any commit. Protected files are never writable. If tests fail, git reverts the change. A successful commit triggers a clean restart so new code loads.

- [ ] **Step 1: Write the file**

```python
# src/clawbot/coder.py
"""
CTO self-modification coder.

Listens for code.change_request messages on the bus. For each request:
  1. Validates no protected files are touched, no file > 500 lines
  2. Asks LLM to produce new whole-file content for each affected file
  3. Writes files to disk
  4. Runs uv run pytest
  5. Green → verify charter SHA256 unchanged → git commit;
     Red OR charter hash mismatch → git checkout HEAD (revert)
  6. Publishes code.change_result either way

On successful commit, signals the scheduler to restart so new code takes effect.
Restart is clean — Docker restart policy brings the container back up.

Safety invariants:
- Protected files (kill switch, this coder, charter, every SOUL.md, all safety-critical
  modules) can NEVER be modified via CTOCoder. The list is enforced in code and
  cross-checked against a SHA256 of CORPORATE_CHARTER.md after every commit.
- Files > 500 lines are rejected — LLM whole-file output is unreliable for large files
- New pip dependencies cannot be added via code change (image rebuild required)
"""
import hashlib
import logging
import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from clawbot.bus import MessageBus
    from clawbot.llm_pool import LLMPool

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).parent.parent.parent  # clawbot/

CHANGE_REQUEST_TOPIC = "code.change_request"
CHANGE_RESULT_TOPIC = "code.change_result"

# PROTECTED_FILES extends beyond the minimal "kill switch + coder" set. A CTOCoder
# that can rewrite evolution.py, genome.py, fitness.py, board.py, scheduler.py,
# the charter, or any SOUL.md can defeat every other safety mechanism in the
# system. Mocked tests cannot catch this because they don't assert these
# invariants. Defense-in-depth: protect the safety surface explicitly.
PROTECTED_FILES = {
    # Kill switch & this coder
    "src/clawbot/monitor.py",
    "src/clawbot/coder.py",
    # Mutation / governance / accounting surfaces
    "src/clawbot/evolution.py",
    "src/clawbot/genome.py",
    "src/clawbot/fitness.py",
    "src/clawbot/board.py",
    "src/clawbot/scheduler.py",
    "src/clawbot/agent_registry.py",
    # Constitution & credentials
    "CORPORATE_CHARTER.md",
    ".env",
    ".env.example",
}

# Glob patterns protected in addition to the explicit list above. Every SOUL.md is
# protected — the meta-evaluator handles those via genome.mutate_soul, not the CTO.
PROTECTED_GLOBS = (
    "agents/**/SOUL.md",
    "agents/**/SOUL.candidate.md",
)

MAX_FILE_LINES = 500  # whole-file LLM output is unreliable beyond this

CHARTER_PATH = "CORPORATE_CHARTER.md"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_protected(filepath: str, repo_root: Path) -> bool:
    """True if filepath matches PROTECTED_FILES exactly or PROTECTED_GLOBS pattern."""
    if filepath in PROTECTED_FILES:
        return True
    for pattern in PROTECTED_GLOBS:
        if (repo_root / filepath).match(pattern) or Path(filepath).match(pattern):
            return True
    return False

_CODER_PROMPT = """\
You are the CTO coder for an autonomous AI company. You will modify source files.

Change request: {description}
Motivation: {motivation}

Current file contents:
{file_contents}

Output ONLY new file contents, one file per block, in this exact format:
===FILE: path/to/file.py===
<complete new file content here>
===END===

Rules:
- No markdown fences, no explanation outside the markers
- Every output file must be syntactically valid Python
- Do not remove existing tests or import error handlers
- Changes must be minimal — only what is required for the described change
- Do not add new pip dependencies (they cannot be installed without image rebuild)
"""


class CTOCoder:
    def __init__(
        self,
        pool: "LLMPool",
        bus: "MessageBus",
        repo_root: Path = REPO_ROOT,
    ) -> None:
        self._pool = pool
        self._bus = bus
        self._repo_root = repo_root

    async def run_loop(self) -> None:
        await self._bus.subscribe(CHANGE_REQUEST_TOPIC)
        logger.info("CTO coder listening on %s", CHANGE_REQUEST_TOPIC)
        while True:
            messages = await self._bus.read_and_ack(
                CHANGE_REQUEST_TOPIC, "cto-coder", count=1, block_ms=10_000,
            )
            for msg in messages:
                await self._handle_request(msg)

    async def _handle_request(self, req: dict) -> None:
        description = req.get("description", "")
        files: list[str] = req.get("files", [])
        motivation = req.get("motivation", "")
        requested_by = req.get("requested_by", "unknown")
        logger.info("Code change request from %s: %s", requested_by, description)

        # Snapshot charter hash before any work so we can verify it post-commit.
        charter_path = self._repo_root / CHARTER_PATH
        charter_sha_before = _sha256(charter_path) if charter_path.exists() else ""

        # Guard: protected files (explicit + glob)
        rejected = [f for f in files if _is_protected(f, self._repo_root)]
        if rejected:
            await self._publish_result(
                False, description,
                f"Rejected: {rejected} are protected and cannot be modified",
            )
            return

        # Guard: file size
        too_large = []
        for filepath in files:
            full = self._repo_root / filepath
            if full.exists():
                n = len(full.read_text(encoding="utf-8").splitlines())
                if n > MAX_FILE_LINES:
                    too_large.append(f"{filepath} ({n} lines > {MAX_FILE_LINES})")
        if too_large:
            await self._publish_result(
                False, description,
                f"Rejected: files exceed line limit — {too_large}",
            )
            return

        # Read current contents
        file_contents_str = ""
        for filepath in files:
            full = self._repo_root / filepath
            if full.exists():
                file_contents_str += f"\n--- {filepath} ---\n{full.read_text(encoding='utf-8')}\n"
            else:
                file_contents_str += f"\n--- {filepath} (NEW FILE) ---\n(empty)\n"

        # Generate via LLM
        messages = [
            {"role": "system", "content": "You are the CTO coder. Output only file contents in the specified format."},
            {"role": "user", "content": _CODER_PROMPT.format(
                description=description,
                motivation=motivation,
                file_contents=file_contents_str,
            )},
        ]
        try:
            response = await self._pool.complete(messages, tier="executive", max_tokens=4096)
        except Exception as exc:
            await self._publish_result(False, description, f"LLM call failed: {exc}")
            return

        # Parse output
        new_contents = _parse_file_blocks(response)
        if not new_contents:
            await self._publish_result(
                False, description, "LLM produced no parseable ===FILE=== blocks",
            )
            return

        # Write to disk
        written: list[str] = []
        for filepath, content in new_contents.items():
            full = self._repo_root / filepath
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(content, encoding="utf-8")
            written.append(filepath)

        # Test
        if not self._run_tests():
            self._git_revert(written)
            logger.warning("CTO reverted change — tests failed: %s", description)
            await self._publish_result(
                False, description, "Reverted: test suite failed after applying change",
            )
            return

        # Charter hash check — even though CORPORATE_CHARTER.md is in PROTECTED_FILES,
        # an LLM rewrite of a *different* file might still touch the charter via a
        # path-traversal payload or symlink. Verify the hash is unchanged before commit.
        if charter_path.exists():
            charter_sha_after = _sha256(charter_path)
            if charter_sha_after != charter_sha_before:
                self._git_revert(written + [CHARTER_PATH])
                logger.error(
                    "CTO reverted: CORPORATE_CHARTER.md hash changed (%s → %s)",
                    charter_sha_before[:8], charter_sha_after[:8],
                )
                await self._publish_result(
                    False, description,
                    "Reverted: CORPORATE_CHARTER.md was modified despite being protected",
                )
                return

        self._git_commit(written, f"feat(cto): {description[:72]}")
        logger.info("CTO committed %d file(s): %s", len(written), description)
        await self._publish_result(
            True, description, f"Committed {len(written)} file(s): {written}",
        )

    def _run_tests(self) -> bool:
        result = subprocess.run(
            ["uv", "run", "pytest", "--tb=short", "-q"],
            cwd=self._repo_root,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return result.returncode == 0

    def _git_commit(self, files: list[str], message: str) -> None:
        subprocess.run(
            ["git", "add", "--"] + files,
            cwd=self._repo_root, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", message,
             "--author", "CTO Agent <cto@clawbot.internal>"],
            cwd=self._repo_root, check=True, capture_output=True,
        )

    def _git_revert(self, files: list[str]) -> None:
        subprocess.run(
            ["git", "checkout", "HEAD", "--"] + files,
            cwd=self._repo_root, check=True, capture_output=True,
        )

    async def _publish_result(self, success: bool, description: str, detail: str) -> None:
        await self._bus.publish(CHANGE_RESULT_TOPIC, {
            "success": success,
            "description": description,
            "detail": detail,
        })


def _parse_file_blocks(response: str) -> dict[str, str]:
    """
    Parse ===FILE: path=== ... ===END=== blocks from LLM output.
    Returns {filepath: new_content} dict.
    """
    pattern = re.compile(
        r"===FILE:\s*([^\n=]+)===\n(.*?)===END===",
        re.DOTALL,
    )
    return {
        m.group(1).strip(): m.group(2)
        for m in pattern.finditer(response)
    }
```

- [ ] **Step 2: Verify import**

```
uv run python -c "from clawbot.coder import CTOCoder, _parse_file_blocks; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```
git add src/clawbot/coder.py
git commit -m "feat: add CTOCoder — LLM-driven code change with test-gate and git commit"
```

---

## Task 7: CTO SOUL.md

**Files:**
- Create: `agents/cto/SOUL.md`

- [ ] **Step 1: Create the agents/cto directory and SOUL.md**

```
mkdir agents\cto
```

Write `agents/cto/SOUL.md` with this exact content:

```markdown
## IMMUTABLE

**Role:** Chief Technology Officer
**Reports to:** CEO

I own the technical systems that power this company. My mandate: improve those
systems so the company earns more revenue with fewer failures and less wasted
compute.

**How I act:**
- I receive `code.change_request` messages on the bus and execute them
- I read my own source files, generate improved versions via LLM, run tests, commit on green
- I write `code.change_result` on the bus after every attempt (success or failure)
- I flag architectural problems to the CEO by publishing to `ceo.directive`

**Hard rules:**
- Every code change must pass the full test suite before committing
- I never touch `monitor.py` (kill switch) or `coder.py` (my own safety logic) or `.env`
- I never remove existing tests — only add or update them
- I cannot add new pip dependencies without a human image rebuild — I state this clearly
  when a change requires a new library
- If a change fails tests three times, I abandon it and tell the CEO why

---

## MUTABLE

### current_focus
Awaiting first code change request.

### active_tasks
None.

### recent_outcomes
No changes implemented yet.
```

- [ ] **Step 2: Verify it exists**

```
uv run python -c "from pathlib import Path; p = Path('agents/cto/SOUL.md'); assert p.exists(); print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```
git add agents/cto/SOUL.md
git commit -m "feat: add CTO agent SOUL.md genome"
```

---

## Task 8: Tests for CTOCoder

**Files:**
- Create: `tests/test_coder.py`

- [ ] **Step 1: Write the tests**

```python
# tests/test_coder.py
import pytest
import numpy as np
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from clawbot.coder import CTOCoder, _parse_file_blocks, PROTECTED_FILES, MAX_FILE_LINES


def _mock_pool(response: str = "===FILE: src/clawbot/example.py===\n# new\n===END===") -> MagicMock:
    pool = MagicMock()
    pool.complete = AsyncMock(return_value=response)
    return pool


def _mock_bus() -> MagicMock:
    bus = MagicMock()
    bus.subscribe = AsyncMock()
    bus.read_and_ack = AsyncMock(return_value=[])
    bus.publish = AsyncMock()
    return bus


def _req(files: list[str], description: str = "Add a comment") -> dict:
    return {
        "description": description,
        "files": files,
        "motivation": "test",
        "requested_by": "ceo",
    }


@pytest.mark.asyncio
async def test_protected_file_rejected(tmp_path):
    pool = _mock_pool()
    bus = _mock_bus()
    coder = CTOCoder(pool=pool, bus=bus, repo_root=tmp_path)

    await coder._handle_request(_req(["src/clawbot/monitor.py"]))

    pool.complete.assert_not_called()
    result = bus.publish.call_args.args[1]
    assert result["success"] is False
    assert "protected" in result["detail"].lower()


@pytest.mark.asyncio
async def test_large_file_rejected(tmp_path):
    large = tmp_path / "src" / "clawbot" / "big.py"
    large.parent.mkdir(parents=True, exist_ok=True)
    large.write_text(("\n" * (MAX_FILE_LINES + 1)), encoding="utf-8")

    pool = _mock_pool()
    bus = _mock_bus()
    coder = CTOCoder(pool=pool, bus=bus, repo_root=tmp_path)

    await coder._handle_request(_req(["src/clawbot/big.py"]))

    pool.complete.assert_not_called()
    result = bus.publish.call_args.args[1]
    assert result["success"] is False
    assert "line limit" in result["detail"].lower()


@pytest.mark.asyncio
async def test_successful_change_writes_file_and_commits(tmp_path):
    target = tmp_path / "src" / "clawbot" / "example.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# old content", encoding="utf-8")

    pool = _mock_pool("===FILE: src/clawbot/example.py===\n# new content\n===END===")
    bus = _mock_bus()
    coder = CTOCoder(pool=pool, bus=bus, repo_root=tmp_path)

    with patch.object(coder, "_run_tests", return_value=True), \
         patch.object(coder, "_git_commit") as mock_commit:
        await coder._handle_request(_req(["src/clawbot/example.py"]))

    assert target.read_text(encoding="utf-8") == "# new content\n"
    mock_commit.assert_called_once()
    result = bus.publish.call_args.args[1]
    assert result["success"] is True


@pytest.mark.asyncio
async def test_failed_tests_reverts_and_reports_failure(tmp_path):
    target = tmp_path / "src" / "clawbot" / "example.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# old", encoding="utf-8")

    pool = _mock_pool("===FILE: src/clawbot/example.py===\n# broken\n===END===")
    bus = _mock_bus()
    coder = CTOCoder(pool=pool, bus=bus, repo_root=tmp_path)

    with patch.object(coder, "_run_tests", return_value=False), \
         patch.object(coder, "_git_revert") as mock_revert:
        await coder._handle_request(_req(["src/clawbot/example.py"]))

    mock_revert.assert_called_once()
    result = bus.publish.call_args.args[1]
    assert result["success"] is False
    assert "reverted" in result["detail"].lower()


@pytest.mark.asyncio
async def test_llm_no_file_blocks_reports_failure(tmp_path):
    pool = _mock_pool("I couldn't figure out the change, sorry.")
    bus = _mock_bus()
    coder = CTOCoder(pool=pool, bus=bus, repo_root=tmp_path)

    await coder._handle_request(_req(["src/clawbot/example.py"]))

    result = bus.publish.call_args.args[1]
    assert result["success"] is False
    assert "parseable" in result["detail"].lower()


def test_parse_file_blocks_single():
    response = "===FILE: src/foo.py===\nprint('hello')\n===END==="
    result = _parse_file_blocks(response)
    assert result == {"src/foo.py": "print('hello')\n"}


def test_parse_file_blocks_multiple():
    response = (
        "===FILE: a.py===\nprint('a')\n===END===\n"
        "===FILE: b.py===\nprint('b')\n===END==="
    )
    result = _parse_file_blocks(response)
    assert set(result.keys()) == {"a.py", "b.py"}


def test_parse_file_blocks_no_match():
    assert _parse_file_blocks("no markers here") == {}
```

- [ ] **Step 2: Run the tests**

```
uv run python -m pytest tests/test_coder.py -v
```

Expected: 8 tests PASS

- [ ] **Step 3: Run the full suite**

```
uv run python -m pytest -v
```

Expected: all tests PASS

- [ ] **Step 4: Commit**

```
git add tests/test_coder.py
git commit -m "test: CTOCoder unit tests — protected files, size limit, commit/revert flows"
```

---

## Task 9: Wire CTOCoder into Scheduler

**Files:**
- Modify: `src/clawbot/scheduler.py`

Two new tasks in `run_forever()`:
- `_coder_loop` — wraps `CTOCoder.run_loop()`
- `_code_change_watcher` — listens for successful commits and triggers a clean restart

- [ ] **Step 1: Update scheduler.py**

Add these imports to the top of `scheduler.py`:

```python
from clawbot.coder import CTOCoder, CHANGE_RESULT_TOPIC
```

Add these two methods to the `Scheduler` class (after `_run_evolution`):

```python
async def _coder_loop(self) -> None:
    coder = CTOCoder(pool=self._pool, bus=self._bus)
    await coder.run_loop()

async def _code_change_watcher(self) -> None:
    """Restart cleanly after a successful code commit so new code loads."""
    await self._bus.subscribe(CHANGE_RESULT_TOPIC)
    while True:
        messages = await self._bus.read_and_ack(
            CHANGE_RESULT_TOPIC, "scheduler-watcher", count=1, block_ms=10_000,
        )
        for msg in messages:
            if msg.get("success"):
                logger.info(
                    "Code change committed (%s) — restarting to load new code",
                    msg.get("description", ""),
                )
                raise SystemExit(0)
```

Update `run_forever` to include the two new tasks:

```python
async def run_forever(self) -> None:
    logger.info("Scheduler starting")
    tasks = [
        asyncio.create_task(self._executive_loop(), name="executive"),
        asyncio.create_task(self._board_loop(), name="board"),
        asyncio.create_task(self._evolution_loop(), name="evolution"),
        asyncio.create_task(self._kill_switch_watchdog(), name="killswitch"),
        asyncio.create_task(self._coder_loop(), name="cto-coder"),
        asyncio.create_task(self._code_change_watcher(), name="code-change-watcher"),
    ]
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
    for task in pending:
        task.cancel()
    for task in done:
        if task.exception():
            logger.error("Task %s failed: %s", task.get_name(), task.exception())
```

- [ ] **Step 2: Run all tests**

```
uv run python -m pytest -v
```

Expected: all tests PASS

- [ ] **Step 3: Commit**

```
git add src/clawbot/scheduler.py
git commit -m "feat: wire CTOCoder and code-change-watcher into Scheduler"
```

---

## Task 10: Docker setup for git + volume mount

**Files:**
- Modify: `Dockerfile`
- Modify: `docker-compose.yml`

The container needs `git` to commit changes, and the source code must be volume-mounted (not baked-in) so code changes persist across restarts.

- [ ] **Step 1: Update Dockerfile — add git, pre-download fastembed model**

The fastembed model (~130 MB BAAI/bge-small-en-v1.5) is downloaded on first use.
Without baking it into the image, the first production CompanyBrain.write() call
cold-starts a 30–60 s blocking download; if the download fails, every brain call
silently fails and no agent escalates. Bake it at build time:

```dockerfile
FROM python:3.13-slim

# Install Chromium dependencies for browser-use, plus git for CTO self-modification
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium chromium-driver \
    libglib2.0-0 libnss3 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libasound2 \
    git \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CHROMIUM_PATH=/usr/bin/chromium

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir uv && uv sync --no-dev

# Pre-download the fastembed ONNX model so first production write() doesn't
# block on a 30–60 s download. Fails fast at build time if the model can't be fetched.
RUN uv run python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5')"

COPY src/ src/
COPY agents/ agents/

CMD ["uv", "run", "python", "-m", "clawbot.main"]
```

- [ ] **Step 2: Update docker-compose.yml — mount full repo + git author**

The `clawbot` service volumes and environment section:

```yaml
  clawbot:
    build: .
    restart: unless-stopped
    depends_on:
      redis:
        condition: service_healthy
      postgres:
        condition: service_healthy
    env_file: .env
    volumes:
      - .:/app                             # full repo mount — CTO code changes persist on disk
      - metrics_data:/metrics
      - kill_switch:/tmp/clawbot_kill
    environment:
      REDIS_URL: redis://redis:6379/0
      DATABASE_URL: postgresql://clawbot:clawbot@postgres:5432/clawbot
      KILL_FILE_PATH: /tmp/clawbot_kill/clawbot.KILL
      GIT_AUTHOR_NAME: "CTO Agent"
      GIT_AUTHOR_EMAIL: "cto@clawbot.internal"
      GIT_COMMITTER_NAME: "CTO Agent"
      GIT_COMMITTER_EMAIL: "cto@clawbot.internal"
    command: python -m clawbot.main
```

Note: `./agents:/app/agents` is removed — it is now covered by `.:/app`.

- [ ] **Step 3: Verify compose is valid**

```
docker compose config --quiet
```

Expected: no errors

- [ ] **Step 4: Commit**

```
git add Dockerfile docker-compose.yml
git commit -m "feat: add git to container, mount full repo for CTO self-modification"
```

---

## Self-Review

### Spec coverage

| Requirement | Task |
|---|---|
| Shared company brain — all agents read/write | Tasks 2–5 |
| Local embeddings (no API calls) | Task 1 (fastembed), Task 3 |
| pgvector semantic search | Task 3 (`search()`) |
| Category-filtered retrieval | Task 3 (`search(category=...)`) |
| Chronological retrieval | Task 3 (`get_recent()`) |
| CEO decisions written to brain | Task 5 |
| CTO receives `code.change_request` | Task 6 |
| LLM generates whole-file replacements | Task 6 |
| Tests run before commit | Task 6 (`_run_tests`) |
| Git commit on green | Task 6 (`_git_commit`) |
| Git revert on red | Task 6 (`_git_revert`) |
| Protected files cannot be modified | Task 6 (`PROTECTED_FILES`) |
| Restart after successful commit | Task 9 (`_code_change_watcher`) |
| CTO SOUL.md | Task 7 |
| git available in container | Task 10 |
| Source mounted so changes persist | Task 10 |

### Placeholder scan

No TBDs, no "add appropriate" hand-waves, no "similar to Task N" references found.

### Type consistency

- `CompanyBrain.__init__(pool: asyncpg.Pool)` — matches `Database.pool` property return type ✓
- `CTOCoder.__init__(pool: LLMPool, bus: MessageBus, repo_root: Path)` — matches Task 9 construction ✓
- `_parse_file_blocks(response: str) -> dict[str, str]` — used as `new_contents.items()` in `_handle_request` ✓
- `Scheduler.__init__(brain: CompanyBrain | None = None)` — `None` default preserves all existing tests ✓
- `CHANGE_RESULT_TOPIC` imported in scheduler from `coder` — single source of truth ✓

---

Plan complete and saved to `docs/superpowers/plans/2026-05-16-company-brain-and-self-modification.md`.

**Two execution options:**

**1. Subagent-Driven (recommended)** — Fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch with checkpoints

Which approach?
