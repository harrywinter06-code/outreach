"""
Execution kernel — converts executive directives into real actions.

Subscribes to all *.directive bus topics. For each message:
1. Records a depth-0 chain event (executive issued directive)
2. Parses the action field from the JSON response
3. Dispatches to the registered handler
4. Records a depth-1 chain event (action executed)
5. Acks the message ONLY on full success (at-least-once delivery)

At-least-once: handler failure leaves the message in the Redis pending list
for the next poll. All handlers must be idempotent.
Malformed JSON: acked immediately (retry is futile for parse errors).
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from clawbot.json_util import extract_json

if TYPE_CHECKING:
    from clawbot.agent_factory import AgentFactory
    from clawbot.agent_registry import AgentRegistry
    from clawbot.bus import MessageBus
    from clawbot.causal_store import CausalStore
    from clawbot.company_brain import CompanyBrain
    from clawbot.task_store import TaskStore

logger = logging.getLogger(__name__)

DIRECTIVE_TOPICS = [
    "ceo.directive", "cfo.directive", "cmo.directive",
    "coo.directive", "cto.directive",
]
_POLL_BLOCK_MS = 200
_UNKNOWN_CHAIN = "00000000-0000-0000-0000-000000000000"


class DirectiveRouter:
    def __init__(
        self,
        bus: "MessageBus",
        causal_store: "CausalStore",
        registry: "AgentRegistry",
        agent_factory: "AgentFactory",
        task_store: "TaskStore",
        metrics_dir: Path,
        brain: "CompanyBrain | None" = None,
        db_pool=None,  # asyncpg.Pool | None; required for plan injection
    ) -> None:
        self._bus = bus
        self._causal_store = causal_store
        self._registry = registry
        self._factory = agent_factory
        self._task_store = task_store
        self._metrics_dir = metrics_dir
        self._brain = brain
        self._db_pool = db_pool

    async def run(self) -> None:
        """Continuous poll loop. Runs until cancelled."""
        while True:
            await self._poll_once()
            await asyncio.sleep(0)

    async def _poll_once(self) -> None:
        for topic in DIRECTIVE_TOPICS:
            try:
                messages = await self._bus.read(
                    topic, "directive-router", count=5, block_ms=_POLL_BLOCK_MS,
                )
            except Exception as exc:
                logger.error("Bus read failed for topic %s: %s", topic, exc)
                continue
            for msg in messages:
                await self._handle_message(topic, msg)

    async def _handle_message(self, topic: str, msg: dict) -> None:
        msg_id: str = msg["_id"]
        chain_id: str = msg.get("chain_id") or _UNKNOWN_CHAIN
        from_agent = topic.split(".")[0]

        try:
            data = extract_json(msg.get("response", ""))
        except (ValueError, Exception):
            logger.warning("DirectiveRouter: malformed JSON in %s — acking to clear", topic)
            await self._bus.ack(topic, msg_id)
            return

        action = str(data.get("action", "")).strip().lower()
        # wait is a valid no-op: ack immediately, no CAG event.
        # Recording depth-0 for every wait would inflate chain counts and
        # let executives game attribution_rate by issuing cheap wait directives.
        if not action or action == "wait":
            await self._bus.ack(topic, msg_id)
            return

        # depth-0: executive issued this directive
        try:
            await self._causal_store.record_event(
                chain_id=chain_id,
                agent_id=from_agent,
                action_type="directive",
                causal_depth=0,
            )
        except Exception as exc:
            logger.error("CAG depth-0 record failed for chain %s: %s", chain_id, exc)
            return  # do NOT ack

        handler = self._get_handler(action)
        if handler is None:
            logger.warning("DirectiveRouter: unknown action '%s' from %s", action, from_agent)
            await self._bus.ack(topic, msg_id)
            return

        try:
            await handler(data, chain_id, from_agent)
            await self._causal_store.record_event(
                chain_id=chain_id,
                agent_id="router",
                action_type=action,
                causal_depth=1,
                metadata={"directive": str(data.get("directive", ""))[:200]},
            )
            await self._bus.ack(topic, msg_id)
        except Exception as exc:
            logger.error("DirectiveRouter: handler '%s' failed for chain %s: %s", action, chain_id, exc)
            # do NOT ack — stays in pending for retry

    def _get_handler(self, action: str):
        hardcoded = {
            "hire": self._handle_hire,
            "fire": self._handle_fire,
            "assign_task": self._handle_assign_task,
            "publish_product": self._handle_publish_product,
            "message": self._handle_message_action,
            "web_research": self._handle_web_research,
            "plan_init": self._handle_plan_init,
            "plan_advance": self._handle_plan_advance,
            "plan_pivot": self._handle_plan_pivot,
            # web_search and browser_task handlers from 100-hands plan, if present:
        }
        if hasattr(self, "_handle_web_search"):
            hardcoded["web_search"] = self._handle_web_search
        if hasattr(self, "_handle_browser_task"):
            hardcoded["browser_task"] = self._handle_browser_task
        if action in hardcoded:
            return hardcoded[action]

        # Fallback: any registered skill becomes an action.
        from clawbot.skill_registry import REGISTRY
        if REGISTRY is not None and REGISTRY.get_meta(action) is not None:
            async def _wrapper(data: dict, chain_id: str, from_agent: str) -> None:
                # Skills consume the whole `data` minus framing fields as params.
                framing = {"action", "directive", "priority", "next_wakeup_s", "escalate"}
                params = {k: v for k, v in data.items() if k not in framing}
                await self._handle_skill_call(action, params, chain_id, from_agent)
            return _wrapper
        return None

    async def _handle_hire(self, data: dict, chain_id: str, from_agent: str) -> None:
        role = str(data.get("role", data.get("directive", "analyst")))[:80]
        mandate = str(data.get("mandate", data.get("directive", "Generate revenue.")))[:400]
        supervisor = str(data.get("supervisor", from_agent))[:40]
        pool = getattr(self._factory, "_pool", None)
        await self._factory.spawn(
            role=role,
            supervisor=supervisor,
            mandate=mandate,
            pool=pool,
        )
        logger.info("Hired new agent: role=%s supervisor=%s", role, supervisor)

    async def _handle_fire(self, data: dict, chain_id: str, from_agent: str) -> None:
        agent_id = str(data.get("agent_id", data.get("directive", "")))[:60]
        if not agent_id:
            raise ValueError("fire action missing agent_id")
        await self._factory.fire(agent_id)
        logger.info("Fired agent: %s", agent_id)

    async def _handle_assign_task(self, data: dict, chain_id: str, from_agent: str) -> None:
        assigned_to = str(data.get("assigned_to", ""))[:60]
        title = str(data.get("title", data.get("directive", "task")))[:120]
        description = str(data.get("description", data.get("directive", "")))[:1000]
        if not assigned_to:
            raise ValueError("assign_task missing assigned_to")
        spec = await self._registry.get(assigned_to)
        if spec is None:
            raise ValueError(f"assign_task: agent '{assigned_to}' not found in registry")
        # TaskStore.create_task is synchronous — call without await
        self._task_store.create_task(
            title=title,
            description=description,
            assigned_to=assigned_to,
            chain_id=chain_id,
        )
        logger.info("Assigned task '%s' to %s", title, assigned_to)

    async def _handle_publish_product(self, data: dict, chain_id: str, from_agent: str) -> None:
        title = str(data.get("title", data.get("directive", "new product")))[:200]
        description = str(data.get("description", ""))[:2000]
        from clawbot.escalation import escalate
        await escalate(
            bus=self._bus,
            severity="request",
            summary=f"New product needs Gumroad listing: {title}",
            detail=(
                f"Product title: {title}\n\nDescription: {description}\n\n"
                f"CAG chain_id: {chain_id}\n\n"
                "Create this product at https://app.gumroad.com/products/new "
                "then reply with: PRODUCT_URL:<url> CHAIN:<chain_id>"
            ),
            from_agent=from_agent,
        )
        logger.info("Escalated publish_product for '%s' (chain=%s)", title, chain_id)

    async def _handle_message_action(self, data: dict, chain_id: str, from_agent: str) -> None:
        target = str(data.get("target", data.get("assigned_to", "")))[:60]
        content = str(data.get("message", data.get("directive", "")))[:1000]
        if not target:
            raise ValueError("message action missing target")
        await self._bus.publish_inbox(
            target,
            {"from": from_agent, "message": content, "chain_id": chain_id},
        )
        logger.info("Sent message from %s to %s", from_agent, target)

    async def _handle_web_research(self, data: dict, chain_id: str, from_agent: str) -> None:
        from clawbot.web_researcher import fetch_and_extract
        url = str(data.get("url", ""))[:500]
        query = str(data.get("query", "web research"))[:200]
        if not url:
            raise ValueError("web_research missing url")
        try:
            content = await fetch_and_extract(url)
        except Exception as exc:
            raise RuntimeError(f"Web fetch failed for {url}: {exc}") from exc
        if self._brain is not None:
            await self._brain.write(
                f"Web research [{query}] from {url}:\n{content}",
                category="research",
                metadata={"url": url, "query": query, "chain_id": chain_id},
            )
        logger.info("Web research complete: %s (%d chars)", url, len(content))

    async def _handle_skill_call(
        self, skill_name: str, params: dict, chain_id: str, from_agent: str,
    ) -> None:
        """Dispatch a registered skill, publish result to caller inbox.

        The reason this is the integration point (rather than agents calling
        the registry directly): every action already flows through this router,
        gets CAG-logged, gets ack semantics, gets one error-handling surface.
        Skills inherit all of that for free.
        """
        from clawbot.skill_registry import REGISTRY
        from clawbot.skill_ctx import make_live_ctx
        from clawbot.config import settings
        if REGISTRY is None:
            raise RuntimeError("skill registry not initialised")

        ctx = make_live_ctx(
            caller_id=from_agent,
            budget_usd=0.10,  # per-call soft cap; daily cap still applies via Monitor
            llm_pool=getattr(self._factory, "_pool", None),
            bus=self._bus,
            brain=self._brain,
            db_pool=getattr(self, "_db_pool", None),
            escalation=None,
            secret_allowlist=[
                "GUMROAD_API_KEY", "STRIPE_SECRET_KEY",
                "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
                "STRIPE_ISSUING_CARDHOLDER_ID",
                "PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET",
                "COINBASE_COMMERCE_API_KEY",
                # Publishing-pack credentials (Phase H Task 27)
                "SUBSTACK_EMAIL", "SUBSTACK_PASSWORD", "SUBSTACK_PUBLICATION_URL",
                "MEDIUM_INTEGRATION_TOKEN", "MEDIUM_USER_ID",
                "DEVTO_API_KEY",
                "HASHNODE_PAT", "HASHNODE_PUBLICATION_ID",
                "BSKY_HANDLE", "BSKY_APP_PASSWORD",
                "MASTODON_INSTANCE", "MASTODON_ACCESS_TOKEN",
                "BUFFER_ACCESS_TOKEN",
            ],
            workspace_root=str(self._metrics_dir / "workspace"),
            fs_allowed_roots=[
                str(self._metrics_dir.parent / "agents" / "skills"),
                str(self._metrics_dir.parent / "agents" / "workers"),
                str(self._metrics_dir.parent / "data"),
            ],
            stripe_secret_key=settings.stripe_secret_key,
            tavily_api_key=settings.tavily_api_key,
            firecrawl_api_key=settings.firecrawl_api_key,
            accounts_vault_key=settings.accounts_vault_key,
            accounts_db_path=settings.accounts_db_path,
            imap_host=settings.imap_host,
            imap_port=settings.imap_port,
            imap_user=settings.imap_user,
            imap_password=settings.imap_password,
            email_domain=settings.email_domain,
            gumroad_api_key=settings.gumroad_api_key,
            paypal_client_id=settings.paypal_client_id,
            paypal_client_secret=settings.paypal_client_secret,
            paypal_environment=settings.paypal_environment,
            coinbase_commerce_api_key=settings.coinbase_commerce_api_key,
        )

        record = await REGISTRY.call(skill_name, params, ctx)

        # Only record live calls for actual execution attempts (not param-validation rejections).
        _is_param_error = record.error is not None and record.error.startswith("missing required param")
        if not _is_param_error:
            REGISTRY._record_live_call(skill_name, record.ok)
        if not record.ok and not _is_param_error and REGISTRY.is_canary(skill_name):
            logger.warning("Canary failure for %s — demoting", skill_name)
            REGISTRY.demote_on_canary_failure(skill_name, reason=record.error or "unknown")
            await self._bus.publish_inbox(from_agent, {
                "from": f"skill:{skill_name}",
                "ok": False,
                "message": (
                    f"Skill {skill_name} failed canary and was demoted. "
                    "Author a replacement via skill_request."
                ),
                "chain_id": chain_id,
            })
            return

        if record.ok:
            summary = str(record.result)[:1500]
            await self._bus.publish_inbox(from_agent, {
                "from": f"skill:{skill_name}",
                "ok": True,
                "message": f"{skill_name} returned: {summary}",
                "chain_id": chain_id,
            })
            if self._brain is not None:
                try:
                    await self._brain.write(
                        f"Skill call [{skill_name}] params={params}: {summary}",
                        category="skill_result",
                        metadata={"skill": skill_name, "chain_id": chain_id},
                    )
                except Exception:
                    pass
            logger.info("Skill complete: %s for %s (%dms)", skill_name, from_agent, record.latency_ms)
        else:
            await self._bus.publish_inbox(from_agent, {
                "from": f"skill:{skill_name}",
                "ok": False,
                "message": f"{skill_name} failed: {record.error}",
                "chain_id": chain_id,
            })
            logger.warning("Skill failed: %s for %s — %s", skill_name, from_agent, record.error)

    async def _handle_plan_init(self, data: dict, chain_id: str, from_agent: str) -> None:
        from clawbot.plan_store import PlanStore
        store = getattr(self, "_plan_store", None)
        if store is None:
            pool = getattr(self, "_db_pool", None)
            if pool is None:
                raise RuntimeError(
                    "plan_* actions unavailable: DirectiveRouter has no db_pool wired"
                )
            store = PlanStore(pool)
        hypothesis = str(data.get("hypothesis", ""))[:400]
        milestones = data.get("milestones", [])
        if not isinstance(milestones, list) or not milestones:
            raise ValueError("plan_init requires non-empty milestones list")
        await store.create_plan(
            agent_id=from_agent, hypothesis=hypothesis, milestones=milestones,
        )
        logger.info("Plan initialised for %s with %d milestones", from_agent, len(milestones))

    async def _handle_plan_advance(self, data: dict, chain_id: str, from_agent: str) -> None:
        from clawbot.plan_store import PlanStore
        store = getattr(self, "_plan_store", None)
        if store is None:
            pool = getattr(self, "_db_pool", None)
            if pool is None:
                raise RuntimeError(
                    "plan_* actions unavailable: DirectiveRouter has no db_pool wired"
                )
            store = PlanStore(pool)
        advanced = await store.advance_milestone(agent_id=from_agent)
        logger.info(
            "Plan advance for %s: %s",
            from_agent,
            "next milestone active" if advanced else "plan complete",
        )

    async def _handle_plan_pivot(self, data: dict, chain_id: str, from_agent: str) -> None:
        from clawbot.plan_store import PlanStore
        store = getattr(self, "_plan_store", None)
        if store is None:
            pool = getattr(self, "_db_pool", None)
            if pool is None:
                raise RuntimeError(
                    "plan_* actions unavailable: DirectiveRouter has no db_pool wired"
                )
            store = PlanStore(pool)
        reason = str(data.get("reason", ""))[:400]
        new_hypothesis = str(data.get("new_hypothesis", ""))[:400]
        new_milestones = data.get("new_milestones", [])
        if not new_milestones:
            raise ValueError("plan_pivot requires new_milestones")
        await store.pivot(
            agent_id=from_agent, reason=reason,
            new_hypothesis=new_hypothesis, new_milestones=new_milestones,
        )
        logger.info("Plan pivot for %s: %s", from_agent, reason[:80])
