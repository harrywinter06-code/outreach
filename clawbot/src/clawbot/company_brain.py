"""
Shared company knowledge store — all agents read/write here.
Uses pgvector with local ONNX embeddings (fastembed, no API calls, no PyTorch).

The `_embed` method runs synchronously inside a thread executor so the scheduler
event loop is not blocked for ~50–200 ms per write. At board-meeting fanout
(5 shareholder calls + executive cycle, each writing decisions), synchronous
embedding would block the event loop for ~1 s, misfiring the rate-limit
minute-bucket arithmetic in llm_pool.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

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

    def __init__(self, pool: Any) -> None:
        # pool typed as Any so this module imports cleanly without asyncpg installed
        # (tests inject a MagicMock; production passes an asyncpg.Pool).
        self._pool = pool

    def _embed_sync(self, text: str) -> np.ndarray:
        """CPU-bound — must NOT be called directly from the event loop.

        Returns float32: pgvector's `vector` column expects float32 wire format.
        fastembed currently returns float32 by default but the cast is cheap
        insurance against a model swap or library upgrade silently producing
        float64 (which pgvector would refuse with an unhelpful error)."""
        vec = np.array(list(_get_model().embed([text]))[0])
        return vec.astype(np.float32, copy=False)

    async def _embed(self, text: str) -> np.ndarray:
        """Run the CPU-bound embedding in the default executor."""
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
        """Return up to k entries ordered by cosine similarity to query."""
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

    async def prune_older_than(self, category: str, max_age_days: int) -> int:
        """Delete entries in this category older than max_age_days. Returns count deleted.

        Required for high-write categories like 'market_signal' (opportunity scanner
        writes up to ~480 entries/day) — without retention the embedding column
        grows ~250 KB/day per category indefinitely.
        """
        result = await self._pool.execute(
            """DELETE FROM knowledge
               WHERE category = $1
                 AND created_at < NOW() - ($2 || ' days')::interval""",
            category, str(int(max_age_days)),
        )
        # asyncpg execute() returns "DELETE <n>"
        try:
            return int(str(result).split()[-1])
        except (ValueError, IndexError):
            return 0


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
