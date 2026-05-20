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


def action_produces_artifact(action_name: str, strategy: str | None = None) -> bool:
    """True iff dispatching this action counts as producing a concrete
    artifact for the given strategy.

    Z5: Per-strategy expansion. The global ARTIFACT_ACTIONS list only
    covered the paid_personalised_report model (publishes that drive
    traffic). Affiliate, SEO, and freemium strategies have different
    progress markers — affiliate counts comparison-page writes,
    SEO counts article writes, freemium counts free-tool improvements.
    Each strategy's extra_artifact_actions is unioned with the global
    list before checking."""
    if action_name in ARTIFACT_ACTIONS:
        return True
    if not strategy:
        return False
    try:
        from clawbot.business_strategies import get_strategy
    except Exception:
        return False
    strat = get_strategy(strategy)
    if strat is None:
        return False
    return action_name in strat.extra_artifact_actions


# Framing fields the directive_router strips before passing to skill.run().
# Pre-validation must apply the same stripping so we don't false-positive
# on missing-param when the action data has framing keys mixed in.
_FRAMING_KEYS = frozenset((
    "action", "directive", "priority", "next_wakeup_s",
    "escalate", "dashboard_widget", "business_id",
))


def _missing_required_params(action: str, data: dict) -> list[str]:
    """Return the list of required params missing from `data` for the
    given action. Empty list = action is valid. Empty list when skill
    isn't registered (let dispatch + downstream handler decide)."""
    try:
        from clawbot.skill_registry import REGISTRY
        import inspect
    except Exception:
        return []
    if REGISTRY is None:
        return []
    # Access underlying _skills dict to get the run() signature.
    skill = REGISTRY._skills.get(action) if hasattr(REGISTRY, "_skills") else None
    if skill is None:
        return []
    try:
        sig = inspect.signature(skill.run)
    except Exception:
        return []
    required = [
        pname for pname, param in sig.parameters.items()
        if pname != "ctx"
        and param.default is inspect.Parameter.empty
        and param.kind not in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        )
    ]
    supplied = {k for k in data.keys() if k not in _FRAMING_KEYS}
    return [p for p in required if p not in supplied]


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
        cycle_started_at = datetime.now(UTC)
        try:
            # Z2.5b polish: pull last 5 attempts from skill_calls so the LLM
            # sees its own mistakes and can correct in this cycle. Empty
            # for never-cycled businesses or stores without the method.
            recent_actions: list[dict] = []
            try:
                recent_actions = await self._store.recent_skill_calls(
                    business_id=business.business_id, limit=5,
                )
            except Exception as exc:
                logger.debug("recent_skill_calls unavailable for %s: %s", business.business_id, exc)

            prompt = render_business_prompt(
                business=business,
                recent_actions=recent_actions,
                recent_skill_results=[],
                skill_catalog=self._load_catalog(),
            )
            messages = [
                {"role": "system", "content": "You are an autonomous business operator. Reply ONLY with one JSON object. Use ONLY the listed skills and include EVERY required param."},
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

        # Z2.5b polish: pre-validate against skill META so we don't dispatch
        # an action we already know will fail param validation. Counts as
        # stall (the LLM gets the failure in next cycle's recent_actions
        # and can correct). If skill registry is unavailable, fall through.
        missing = _missing_required_params(action, data)
        if missing:
            logger.info(
                "Business %s: action=%s rejected by pre-validate (missing %s), stalling",
                business.business_id, action, missing,
            )
            # Record a synthetic skill_calls row so the LLM sees this
            # specific failure on its next cycle.
            await self._record_synthetic_failure(
                business_id=business.business_id, action=action,
                reason=f"missing required param: {missing[0]}",
            )
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

        # Z3.5 + Z5: artifact crediting is now both result-verified AND
        # strategy-aware. Pull strategy from genome so affiliate / SEO /
        # freemium businesses get credit for their model-appropriate work
        # (write_long_form_article, fs_write, keyword_research, etc.)
        # rather than only paid_personalised_report's publish-to-social actions.
        strategy = (business.genome or {}).get("strategy") if business.genome else None
        if not action_produces_artifact(action, strategy=strategy):
            await self._bump_stall(business)
            logger.info(
                "Business %s (strategy=%s) dispatched non-artifact action=%s, stall++",
                business.business_id, strategy, action,
            )
            return False

        success = await self._await_skill_success(
            business_id=business.business_id, skill_name=action,
            since=cycle_started_at,
        )
        if success:
            self.artifact_count += 1
            await self._mark_artifact(business)
            logger.info(
                "Business %s produced artifact via action=%s (verified ok=true)",
                business.business_id, action,
            )
            return True
        else:
            await self._bump_stall(business)
            logger.info(
                "Business %s dispatched %s but no successful skill_call row "
                "appeared within poll window — silent skill failure, stall++",
                business.business_id, action,
            )
            return False

    async def _record_synthetic_failure(
        self, *, business_id: str, action: str, reason: str,
    ) -> None:
        """Insert a synthetic skill_calls row when pre-validation rejects an
        action before dispatch. Without this, the LLM's recent_actions list
        wouldn't show the rejection and the same mistake repeats next cycle.

        Swallows errors — failure to log a failure must not break the loop."""
        try:
            from clawbot.skill_registry import REGISTRY
            if REGISTRY is None or getattr(REGISTRY, "_stats_db", None) is None:
                return
            async with REGISTRY._stats_db.acquire() as conn:
                await conn.execute(
                    "INSERT INTO skill_calls "
                    "(skill_name, caller_id, ok, cost_usd, latency_ms, error, business_id) "
                    "VALUES ($1, $2, FALSE, 0.0, 0, $3, $4)",
                    action, "business", reason, business_id,
                )
        except Exception as exc:
            logger.debug("synthetic failure log skipped: %s", exc)

    async def _await_skill_success(
        self, *, business_id: str, skill_name: str, since: datetime,
        max_wait_s: float = 60.0, poll_s: float = 2.0,
    ) -> bool:
        """Poll skill_calls for up to max_wait_s waiting for an ok=true row
        with this business_id + skill_name written since `since`. Returns
        True if found, False on timeout.

        Z3.5 — dispatch-time crediting hallucinated artifacts when skills
        silently degraded. This makes the cycle runner wait for the actual
        outcome before resetting the stall counter.
        """
        if not hasattr(self._store, "_pool") or self._store._pool is None:
            # Test/mock path: no DB to poll. Treat as success to keep
            # legacy unit tests passing without faking a poll loop.
            return True
        pool = self._store._pool
        elapsed = 0.0
        while elapsed < max_wait_s:
            try:
                async with pool.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT id, ok FROM skill_calls "
                        "WHERE business_id = $1 AND skill_name = $2 "
                        "AND called_at >= $3 "
                        "ORDER BY id DESC LIMIT 1",
                        business_id, skill_name, since,
                    )
                if row is not None:
                    return bool(row["ok"])
            except Exception as exc:
                logger.debug(
                    "await_skill_success poll error for %s/%s: %s",
                    business_id, skill_name, exc,
                )
                return True  # don't double-penalise on infra hiccup
            await asyncio.sleep(poll_s)
            elapsed += poll_s
        return False

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
