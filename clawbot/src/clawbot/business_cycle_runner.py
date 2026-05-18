"""
Swarm Z2.5 Task B — BusinessCycleRunner.

Long-running scheduler loop. Each tick:
1. Pick the active business with the oldest `last_cycle_at` (round-robin).
2. Render a genome-scoped prompt via business_prompt_renderer.
3. Get an action via LLMPool (worker tier — cheaper, saves rate limit).
4. Parse JSON, inject business_id into the action data, publish to
   `<business_id>.directive` bus topic. DirectiveRouter picks it up with
   business_id attribution flowing through to skill_calls.
5. Detect "did this produce an artifact?" — reset stall counter if yes,
   increment if no. Persist via BusinessStore.update_metadata.

Free-tier LLM constraint: one LLM call per business per cycle. With
cap=8 and 30-min interval, 16 calls/hour for the swarm. Negligible
versus NIM 240 RPM budget.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from clawbot.business_store import Business, BusinessStore
from clawbot.business_prompt_renderer import (
    ARTIFACT_ACTIONS,
    render_business_prompt,
)

logger = logging.getLogger(__name__)
UTC = timezone.utc


def _parse_action_json(raw: str) -> dict[str, Any] | None:
    """Extract the first JSON object from an LLM response. Returns None on
    parse failure. Tolerates code-fenced responses (```json ... ```)."""
    if not raw:
        return None
    text = raw.strip()
    # Strip markdown code fence if present
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    # Find first balanced JSON object
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                candidate = text[start : i + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    start = -1
                    continue
    return None


def action_produces_artifact(action_name: str) -> bool:
    """True iff dispatching this action counts as producing a concrete
    artifact (post URL, email sent, payment link created)."""
    return action_name in ARTIFACT_ACTIONS


class BusinessCycleRunner:
    """Round-robin cycle runner over the active business population."""

    def __init__(
        self,
        *,
        store: BusinessStore,
        llm_pool: Any,
        bus: Any,
        stall_threshold: int = 3,
        load_skill_catalog=None,
    ) -> None:
        self._store = store
        self._pool = llm_pool
        self._bus = bus
        self._stall_threshold = stall_threshold
        # Callable returning the current skill catalog (list of entries).
        # Pluggable so tests can inject a mock.
        if load_skill_catalog is None:
            from clawbot.scheduler import _load_skill_catalog
            self._load_catalog = _load_skill_catalog
        else:
            self._load_catalog = load_skill_catalog
        # cumulative counters for telemetry
        self.cycle_count = 0
        self.artifact_count = 0
        self.stall_count = 0

    async def _pick_next_business(self) -> Business | None:
        """Return the active business with the oldest last_cycle_at
        (NULL last_cycle_at sorts first — fresh spawns cycle first)."""
        active = await self._store.list_active()
        if not active:
            return None
        # Sort: never-cycled first, then oldest last_cycle_at
        active.sort(key=lambda b: (b.last_cycle_at is not None, b.last_cycle_at or datetime.min.replace(tzinfo=UTC)))
        return active[0]

    async def run_one_cycle(self, business: Business) -> bool:
        """Run a single business cycle. Returns True if the cycle produced
        a concrete artifact, False otherwise.

        Always advances `last_cycle_at` (via update_fitness with the
        existing score). Always updates `artifact_stall_count` metadata.
        Failures (LLM error, JSON parse error, etc.) count as stall and
        are logged but do not raise.
        """
        self.cycle_count += 1
        try:
            prompt = render_business_prompt(
                business=business,
                recent_actions=[],  # Z2.5b: enrich from skill_calls history if needed
                recent_skill_results=[],
                skill_catalog=self._load_catalog(),
            )
            messages = [
                {"role": "system", "content": "You are an autonomous business operator. Reply ONLY with one JSON object."},
                {"role": "user", "content": prompt},
            ]
            raw = await self._pool.complete(messages, tier="worker", temperature=0.6, max_tokens=800)
        except Exception as exc:
            logger.warning("Business cycle LLM call failed for %s: %s", business.business_id, exc)
            await self._bump_stall(business)
            return False

        data = _parse_action_json(raw)
        if not data or not isinstance(data, dict):
            logger.info("Business %s: LLM returned no parseable JSON, stalling", business.business_id)
            await self._bump_stall(business)
            return False

        action = str(data.get("action", "")).strip().lower()
        if not action or action == "wait":
            logger.info("Business %s: action=wait, stalling", business.business_id)
            await self._bump_stall(business)
            return False

        # Ensure business_id is set on the dispatched action so the
        # directive router attributes the resulting skill_calls correctly.
        data["business_id"] = business.business_id

        # Publish to the shared business.directive topic. The directive
        # router extracts `business_id` from the data dict and threads it
        # into the SkillCtx for skill_calls attribution. Include chain_id
        # so CAG records a clean depth-0 event per cycle.
        import uuid as _uuid
        chain_id = _uuid.uuid4().hex
        await self._bus.publish(
            "business.directive",
            {"response": json.dumps(data), "chain_id": chain_id},
        )

        is_artifact = action_produces_artifact(action)
        if is_artifact:
            self.artifact_count += 1
            await self._mark_artifact(business)
            logger.info(
                "Business %s produced artifact via action=%s",
                business.business_id, action,
            )
        else:
            await self._bump_stall(business)
            logger.info(
                "Business %s dispatched non-artifact action=%s, stall++",
                business.business_id, action,
            )
        return is_artifact

    async def _mark_artifact(self, business: Business) -> None:
        """Reset stall counter and stamp last_cycle_at via update_fitness."""
        await self._store.update_metadata(
            business_id=business.business_id,
            updates={"artifact_stall_count": 0, "last_cycle_artifact": True},
        )
        await self._store.update_fitness(
            business_id=business.business_id, fitness=float(business.fitness_score),
        )

    async def _bump_stall(self, business: Business) -> None:
        """Increment stall counter; stamp last_cycle_at."""
        current = int((business.metadata or {}).get("artifact_stall_count", 0))
        self.stall_count += 1
        await self._store.update_metadata(
            business_id=business.business_id,
            updates={"artifact_stall_count": current + 1, "last_cycle_artifact": False},
        )
        await self._store.update_fitness(
            business_id=business.business_id, fitness=float(business.fitness_score),
        )

    async def run_loop(self, interval_s: float) -> None:
        """Long-running. Per-business cadence is `interval_s` (default 30min) —
        i.e. each business cycles every `interval_s` regardless of population
        size. Per-tick sleep is `interval_s / active_count` so 8 businesses
        get 8 ticks per interval window.

        Cancellation-safe; per-tick errors logged but don't break the loop."""
        while True:
            try:
                business = await self._pick_next_business()
                if business is None:
                    # Swarm empty — wait the interval and check again
                    await asyncio.sleep(interval_s)
                    continue
                await self.run_one_cycle(business)
                active_count = await self._store.count_active()
                tick_sleep = max(15.0, interval_s / max(1, active_count))
            except Exception as exc:
                logger.error("Business cycle tick failed: %s", exc, exc_info=True)
                tick_sleep = interval_s
            await asyncio.sleep(tick_sleep)
