"""
Per-agent revenue attribution via causal chain tracing.

Every market-signal discovery, executive directive, and executed action is
recorded as a chain event with an increasing causal_depth. When a Gumroad
sale is matched to a product registered in product_causal_map, close_chain()
distributes the sale revenue inversely proportional to depth — the originating
signal (depth=0) earns the largest share; mechanical execution (depth=2+)
earns proportionally less.

Attribution formula:
    weight_i = 1 / (causal_depth_i + 1)
    share_i  = revenue * weight_i / sum(all weights in chain)
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncpg

logger = logging.getLogger(__name__)


class CausalStore:
    def __init__(self, pool: "asyncpg.Pool") -> None:
        self._pool = pool

    async def record_event(
        self,
        chain_id: str,
        agent_id: str,
        action_type: str,
        causal_depth: int,
        confidence: float = 1.0,
        metadata: dict | None = None,
    ) -> str:
        """Record a causal event. Returns the generated event_id (UUID string)."""
        event_id: str = await self._pool.fetchval(
            """
            INSERT INTO causal_chain
                (chain_id, agent_id, action_type, causal_depth, confidence, metadata)
            VALUES ($1::uuid, $2, $3, $4, $5, $6::jsonb)
            RETURNING event_id::text
            """,
            chain_id, agent_id, action_type, causal_depth, confidence,
            json.dumps(metadata or {}),
        )
        return event_id

    async def close_chain(self, chain_id: str, revenue_gbp: float) -> None:
        """Distribute revenue_gbp across all open events in chain, weighted inversely
        by causal_depth. Events already closed are skipped."""
        events = await self._pool.fetch(
            "SELECT event_id, causal_depth FROM causal_chain "
            "WHERE chain_id = $1::uuid AND closed_at IS NULL",
            chain_id,
        )
        if not events:
            logger.warning("close_chain: no open events for chain %s", chain_id)
            return
        weights = [1.0 / (row["causal_depth"] + 1) for row in events]
        total = sum(weights)
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                for row, weight in zip(events, weights):
                    share = revenue_gbp * (weight / total)
                    await conn.execute(
                        """UPDATE causal_chain
                           SET attributed_revenue_gbp = $1, closed_at = NOW()
                           WHERE event_id = $2""",
                        share, row["event_id"],
                    )
        logger.info(
            "Closed chain %s: £%.2f distributed across %d events",
            chain_id, revenue_gbp, len(events),
        )

    async def attributed_revenue_7d(self, agent_id: str) -> float:
        """Sum of attributed_revenue_gbp for this agent in the rolling 7-day window."""
        result = await self._pool.fetchval(
            """
            SELECT COALESCE(SUM(attributed_revenue_gbp), 0.0)
            FROM causal_chain
            WHERE agent_id = $1
              AND closed_at IS NOT NULL
              AND ts >= NOW() - INTERVAL '7 days'
            """,
            agent_id,
        )
        return float(result or 0.0)

    async def attribution_rate(self, agent_id: str) -> float:
        """Fraction of chains involving this agent that closed with revenue > 0."""
        total = await self._pool.fetchval(
            "SELECT COUNT(DISTINCT chain_id) FROM causal_chain WHERE agent_id = $1",
            agent_id,
        )
        if not total:
            return 0.0
        with_revenue = await self._pool.fetchval(
            """
            SELECT COUNT(DISTINCT chain_id) FROM causal_chain
            WHERE agent_id = $1
              AND closed_at IS NOT NULL
              AND attributed_revenue_gbp > 0
            """,
            agent_id,
        )
        return float(with_revenue or 0) / float(total)

    async def register_product(
        self,
        gumroad_product_id: str,
        chain_id: str,
        product_title: str,
    ) -> None:
        """Associate a Gumroad product with the causal chain that produced it."""
        await self._pool.execute(
            """
            INSERT INTO product_causal_map (gumroad_product_id, chain_id, product_title)
            VALUES ($1, $2::uuid, $3)
            ON CONFLICT (gumroad_product_id) DO UPDATE
            SET chain_id = $2::uuid, product_title = $3
            """,
            gumroad_product_id, chain_id, product_title,
        )

    async def product_chain_id(self, gumroad_product_id: str) -> str | None:
        """Return the chain_id for this product, or None if unregistered."""
        result: str | None = await self._pool.fetchval(
            "SELECT chain_id::text FROM product_causal_map WHERE gumroad_product_id = $1",
            gumroad_product_id,
        )
        return result

    async def unattributed_sale_products(
        self,
        sale_product_ids: list[str],
    ) -> list[tuple[str, str]]:
        """Return [(gumroad_product_id, chain_id)] for products with open chains."""
        if not sale_product_ids:
            return []
        rows = await self._pool.fetch(
            """
            SELECT p.gumroad_product_id, p.chain_id::text
            FROM product_causal_map p
            WHERE p.gumroad_product_id = ANY($1::text[])
              AND EXISTS (
                SELECT 1 FROM causal_chain c
                WHERE c.chain_id = p.chain_id AND c.closed_at IS NULL
              )
            """,
            sale_product_ids,
        )
        return [(row["gumroad_product_id"], row["chain_id"]) for row in rows]
