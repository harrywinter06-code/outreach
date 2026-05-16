"""
Lateral thinker — weekly cross-signal synthesis.

Reads market_signal entries from the brain, filters to a 14-day freshness
window (FRESHNESS_DAYS), and asks an LLM to identify cross-signal patterns.
Requires at least MIN_SIGNALS=3 fresh signals to avoid synthesising noise.

Output stored in brain as category="lateral_thought".
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from clawbot.company_brain import CompanyBrain
    from clawbot.llm_pool import LLMPool

logger = logging.getLogger(__name__)

MIN_SIGNALS = 3
FRESHNESS_DAYS = 14

_SYNTHESIS_PROMPT = """\
You are a lateral thinking analyst for a UK digital products business.

Below are {n} market signals observed in the past {days} days:

{signals}

Identify cross-signal themes and synthesis insights that no single signal
reveals alone. Look for:
1. Clusters: multiple signals pointing at the same underlying need
2. Timing alignment: signals suggesting the same opportunity window
3. Leverage: one product addressing multiple signals simultaneously
4. Contradictions: signals suggesting a split or confused market

Output a concise synthesis (200-400 words) with 2-4 concrete product ideas
from the cross-signal view. Be specific: name the product, audience, and
why this window exists now.
"""


class LateralThinker:
    def __init__(
        self,
        pool: "LLMPool",
        brain: "CompanyBrain",
    ) -> None:
        self._pool = pool
        self._brain = brain

    async def synthesise(self) -> str | None:
        """Read fresh market signals, synthesise, write to brain. Returns synthesis or None."""
        try:
            entries = await self._brain.search(
                query="market opportunity UK digital product",
                k=20,
                category="market_signal",
            )
        except Exception as exc:
            logger.warning("LateralThinker: brain search failed: %s", exc)
            return None

        cutoff = time.time() - FRESHNESS_DAYS * 86_400
        fresh = [
            e for e in entries
            if float(e.metadata.get("ts", time.time())) >= cutoff
        ]

        if len(fresh) < MIN_SIGNALS:
            logger.info(
                "LateralThinker: %d fresh signals (need %d) — skipping",
                len(fresh), MIN_SIGNALS,
            )
            return None

        signal_text = "\n".join(
            f"[{i+1}] {e.content[:300]}"
            for i, e in enumerate(fresh[:15])
        )
        prompt = _SYNTHESIS_PROMPT.format(
            n=len(fresh[:15]),
            days=FRESHNESS_DAYS,
            signals=signal_text,
        )

        try:
            synthesis = await self._pool.complete(
                [
                    {"role": "system", "content": "You are a lateral thinking analyst."},
                    {"role": "user", "content": prompt},
                ],
                tier="executive",
            )
        except Exception as exc:
            logger.error("LateralThinker: LLM call failed: %s", exc)
            return None

        try:
            await self._brain.write(
                synthesis,
                category="lateral_thought",
                metadata={"signal_count": len(fresh), "ts": time.time()},
            )
        except Exception as exc:
            logger.warning("LateralThinker: brain write failed: %s", exc)

        logger.info("LateralThinker: synthesis complete (%d chars)", len(synthesis))
        return synthesis
